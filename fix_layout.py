import re

with open("/Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/PCB Electronic components/training-dashboard/components/PredictPanel.tsx", "r") as f:
    text = f.read()

# Let's find the main wrappers.
# I will just write a function to extract an element by matching brackets.
def extract_element(start_tag):
    start_idx = text.find(start_tag)
    if start_idx == -1: return ""
    
    # find the end of the open tag
    open_end = text.find(">", start_idx)
    if text[open_end-1] == "/": return text[start_idx:open_end+1] # self closing
    
    count = 1
    i = open_end + 1
    while count > 0 and i < len(text):
        if text.startswith("<div", i):
            count += 1
            i += 4
        elif text.startswith("</div", i):
            count -= 1
            i += 5
        else:
            i += 1
    return text[start_idx:i+1] # +1 for the >

c1 = extract_element('<div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 sm:p-5 rounded-2xl bg-[#141619]/95')
c2 = extract_element('<div className="flex flex-col gap-3 p-4 sm:p-5 rounded-2xl bg-[#141619]/90')
cam_locks = extract_element('{inputMode === "camera" && <CameraLocks')
board_insp = extract_element('<BoardInspection')
c3 = extract_element('<div className="p-4 sm:p-5 rounded-2xl bg-[#141619]/90 border border-[#262930] shadow-sm flex flex-col gap-4"') # check the class
if not c3:
    # let's just use regex for c3
    m = re.search(r'\{\/\* Container 3: Source Card.*?<div[^>]*>', text, re.DOTALL)
    if m:
        c3 = extract_element(m.group(0).split('<div')[-1]) # wait, the class might be different. Let's find it.
        
# A safer way is to just find the indices of the comments.
def extract_between(start_str, end_str):
    s = text.find(start_str)
    e = text.find(end_str, s)
    return text[s:e]

c1 = extract_between("{/* ── Container 1", "{/* Main Grid Wrapper */}")
# Left col has c2, cam_locks, c3
left_col = extract_between("{/* LEFT COLUMN", "{/* ── Right Column")
# Right col has c4, c5, c6, and modals
right_col = extract_between("{/* ── Right Column", "    </div>\n  );\n}")

print("Parsed blocks")
