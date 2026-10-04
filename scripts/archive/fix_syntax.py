with open("/Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/PCB Electronic components/training-dashboard/components/PredictPanel.tsx", "r") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "</form>" in line:
        # The form is closed. Then some divs. Let's insert `)}` after the two divs.
        # Wait, the structure is probably:
        # {showWeightUploadModal && (
        #   <div ...>
        #     <div ...>
        #       <form>
        pass

# Actually let's just insert `)}` at the right place.
# Let's see how many divs are closed after </form>
idx = -1
for i, line in enumerate(lines):
    if "</form>" in line:
        idx = i
        break

if idx != -1:
    # idx+1: </div>
    # idx+2: </div>
    # insert )] at idx+3
    lines.insert(idx+3, "      )}\n")
    with open("/Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/PCB Electronic components/training-dashboard/components/PredictPanel.tsx", "w") as f:
        f.writelines(lines)
    print("Fixed!")
