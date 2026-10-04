import re

with open("frontend/src/components/AOIScanView.tsx", "r") as f:
    lines = f.readlines()

def get_block(start_str, end_str=None, end_offset=0):
    start_idx = -1
    for i, line in enumerate(lines):
        if start_str in line:
            start_idx = i
            break
    if start_idx == -1: return ""
    
    if end_str:
        end_idx = -1
        for i in range(start_idx, len(lines)):
            if end_str in lines[i]:
                end_idx = i + end_offset
                break
        return "".join(lines[start_idx:end_idx+1])
    return ""

print("Stage:", len(get_block("{/* Stage Connection Card */}")))
print("Camera:", len(get_block("{/* Camera Source Selector Card */}")))
