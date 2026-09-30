with open("/Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/PCB Electronic components/training-dashboard/components/PredictPanel.tsx", "r") as f:
    text = f.read()

# The error is at the end of the file.
# Let's print the last 30 lines.
lines = text.split('\n')
for i, l in enumerate(lines[-30:]):
    print(f"{len(lines)-30+i+1}: {l}")
