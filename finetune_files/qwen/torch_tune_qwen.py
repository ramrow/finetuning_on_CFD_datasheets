import os
import torch
from datasets import load_dataset
from accelerate import Accelerator
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    get_scheduler
)
from peft import LoraConfig, get_peft_model
from trl import SFTTrainer, SFTConfig
from torch.optim import AdamW


class CustomSFTTrainer(SFTTrainer):
    def create_optimizer_and_scheduler(self, num_training_steps):
        if self.optimizer is None:
            self.optimizer = AdamW(self.model.parameters(), lr=self.args.learning_rate)
        if self.lr_scheduler is None:
            self.lr_scheduler = get_scheduler(
                name="linear",
                optimizer=self.optimizer,
                num_warmup_steps=0,
                num_training_steps=num_training_steps,
            )

    def train(self, resume_from_checkpoint=None, trial=None, ignore_keys_for_eval=None, **kwargs):
        # Initialize optimizer and scheduler
        num_training_steps = len(self.get_train_dataloader()) * self.args.num_train_epochs
        self.create_optimizer_and_scheduler(num_training_steps)

        model = self.model
        for epoch in range(int(self.args.num_train_epochs)):
            print(f"Starting epoch {epoch + 1}")
    
            for step, batch in enumerate(self.get_train_dataloader()):   
                outputs = model(**batch)
                loss = outputs.loss
                loss.backward()
                self.optimizer.step()
                self.lr_scheduler.step()
                self.optimizer.zero_grad()

                if step % self.args.logging_steps == 0:
                    print(f"Step {step}: Loss = {loss.item()}")

        print("Training is Done")



os.environ["CUDA_VISIBLE_DEVICES"]="0"

quant_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)

def apply_chat_template(example):
    messages = [
        {"role": "system", "content": example["system_prompt"]},
        {"role": "user", "content": example['usr_prompt']},
        {"role": "assistant", "content": example["code_content"]}
    ]
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    return {"text": prompt}

def tokenize_data(example):
    tokens = tokenizer(example['text'], padding="max_length", max_length=1028, truncation=True)
    tokens['labels'] = [
        -100 if token == tokenizer.pad_token_id else token for token in tokens['input_ids']
    ]
    return tokens


ds = (load_dataset("finalform/split_foam",))
model="Qwen/Qwen-7B"
new_model = "qwen-foam"

md = AutoModelForCausalLM.from_pretrained(
    model,
    quantization_config=quant_config,
    device_map="auto",
    # bf16=True,
    trust_remote_code=True,
    torch_dtype=torch.bfloat16,
)
md.config.use_cache = False
md.config.pretraining_tp = 1

tokenizer = AutoTokenizer.from_pretrained(model, trust_remote_code=True)
tokenizer.return_tensors = "pt"
tokenizer.pad_token = '<|endoftext|>'
tokenizer.padding_side = "right"

#######################
tokenizer.chat_template =   "{% for message in messages %}{% if loop.first and message['role'] != 'system' %}" \
                            "{{ '<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n' }}{% endif %}{{ " \
                            "'<|im_start|>' + message['role'] + '\n' + message['content'] + '<|im_end|>\n' }}{% if " \
                            "loop.last and add_generation_prompt %}{{ '<|im_start|>assistant\n' }}{% endif %}{% endfor %}"
#######################

train_ds = ds['train'].map(apply_chat_template)
test_ds = ds['test'].map(apply_chat_template)
tokenized_train_ds = train_ds.map(tokenize_data)
tokenized_test_ds = test_ds.map(tokenize_data)
tokenized_train_ds = tokenized_train_ds.remove_columns(["text", "system_prompt", "usr_prompt", "folder_name", "file_name", "case_path", "description", "code_content"])
tokenized_test_ds = tokenized_test_ds.remove_columns(["text", "system_prompt", "usr_prompt", "folder_name", "file_name", "case_path", "description", "code_content"])

peft_params = LoraConfig(
    lora_alpha=16,
    lora_dropout=0.1,
    r=32, #change rank
    bias="none",
    task_type="CAUSAL_LM",
    target_modules="all-linear"
)

training_args = SFTConfig(
    output_dir="./qwen_results",
    # resume_from_checkpoint="./qwen_results/checkpoint-",
    # compute loss every few steps 1.5k/step
    num_train_epochs=1,
    per_device_train_batch_size=2,
    per_device_eval_batch_size=2,
    gradient_accumulation_steps=2,
    optim="paged_adamw_32bit",
    save_steps=250,
    logging_steps=50,
    learning_rate=3e-4, #2e-4
    weight_decay=0.001,
    fp16=False,
    bf16=True,
    max_grad_norm=0.3,
    max_steps=-1,
    warmup_ratio=0.03,
    # group_by_length=True,
    # lr_scheduler_type="constant",
    report_to="tensorboard",
    packing=False,
    max_length=1028
)

peft_md = get_peft_model(md, peft_params)

trainer = CustomSFTTrainer(
    model= peft_md,
    args=training_args,
    processing_class=tokenizer,
    train_dataset=tokenized_train_ds,
    eval_dataset=tokenized_test_ds,
)
trainer.train()
trainer.model.save_pretrained(new_model)
trainer.processing_class.save_pretrained(new_model)
trainer.evaluate()