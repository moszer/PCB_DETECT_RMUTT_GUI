with open("/Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/PCB Electronic components/training-dashboard/components/PredictPanel.tsx", "r") as f:
    text = f.read()

# Let's count open `<div` and close `</div` in the return block
start = text.find("  return (")
end = text.rfind("  );")
jsx = text[start:end]

open_divs = jsx.count("<div")
close_divs = jsx.count("</div")
print(f"Open: {open_divs}, Close: {close_divs}")
