from datasets import load_dataset
import json

def format_data(example):
    prompt = f"<s>[INST] {example['description']}"
    response = f"{example['foamfiles']}\n\n{example['allrun']}"
    example["text"] = f"{prompt}\n\n[/INST] {response}"
    return example

ds = load_dataset("YYgroup/NL2FOAM")
data = ds.map(format_data)
d = dict()
d['text'] = data['train']['text']
json_object = json.dumps(d, indent=4)

# Writing to sample.json
with open("processed_foam.json", "w") as outfile:
    outfile.write(json_object)

