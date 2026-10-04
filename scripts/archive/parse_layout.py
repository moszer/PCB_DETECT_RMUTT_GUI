with open("/Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/PCB Electronic components/training-dashboard/components/PredictPanel.tsx", "r") as f:
    lines = f.readlines()

def find_line(s, start=0):
    for i in range(start, len(lines)):
        if s in lines[i]:
            return i
    return -1

main_return = find_line("  return (")
print("Main Return:", main_return)

c1_start = find_line("{/* ── Container 1: Top Header Bar ── */}", main_return)
grid_start = find_line('<div className="grid grid-cols-1 lg:grid-cols-12', c1_start)
left_col_start = find_line('<div className="lg:col-span-4', grid_start)
c2_start = find_line("{/* Container 2: Model & Thresholds Card */}", left_col_start)
c3_start = find_line("{/* Container 3: Source Card", c2_start)

# finding where the custom logic for 10 frames check is (ตรวจ Component ครบ - 10 เฟรม)
# The user UI shows it below "ล็อกภาพจากกล้อง"
# Let's search for "ตรวจ Component ครบ"
check_10_start = find_line("ตรวจ Component ครบ - 10 เฟรม")
print("Check 10 Frames:", check_10_start)

right_col_start = find_line('<div className="lg:col-span-8', check_10_start)
c4_start = find_line("{/* Container 4: Main Visualizer Card */}", right_col_start)
c5_start = find_line("{/* Container 5: KPI Summary", c4_start)
c6_start = find_line("{/* Container 6: Detected Components List", c5_start)
grid_end = find_line("</div>", c6_start) # wait, we need to match divs.

print("C2 (Model):", c2_start)
print("C3 (Source):", c3_start)
print("C4 (Vis):", c4_start)
print("C5 (KPI):", c5_start)
print("C6 (Table):", c6_start)

