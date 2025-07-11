from datasets import load_dataset
import json

def format_data(example):
    prompt = f"<s>[INST] {example['description']}"
    response = f"foamfiles:\n{example['foamfiles']}\n\nallrun:\n{example['allrun']}"
    example["text"] = f"{prompt}\n\n[/INST] \n{response}"
    return example

ds = load_dataset("YYgroup/NL2FOAM")
data = ds.map(format_data)
d = dict()
d['text'] = data['train']['text'][0:int(28484/6)]
print(len(d['text']))
json_object = json.dumps(d, indent=4)

with open("truncated_foam.json", "w") as outfile:
    outfile.write(json_object)