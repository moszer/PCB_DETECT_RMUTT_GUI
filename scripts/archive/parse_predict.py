with open("/Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/PCB Electronic components/training-dashboard/components/PredictPanel.tsx", "r") as f:
    lines = f.readlines()

def find_line(s, start=0):
    for i in range(start, len(lines)):
        if s in lines[i]:
            return i
    return -1

main_return = find_line("  return (")

c1 = find_line("{/* ── Container 1: Top Header Bar ── */}", main_return)
grid = find_line('<div className="grid grid-cols-1 lg:grid-cols-12', c1)
col_l = find_line('<div className="lg:col-span-4', grid)
c2 = find_line("{/* Container 2: Model & Thresholds Card */}", col_l)
c3 = find_line("{/* Container 3: Source Card", c2)
cam_locks = find_line("<CameraLocks", c3)
board_insp = find_line("<BoardInspection", c3)

col_r = find_line('<div className="lg:col-span-8', board_insp)
c4 = find_line("{/* Container 4: Main Visualizer Card */}", col_r)
c5 = find_line("{/* Container 5: KPI Summary Metrics Bar & Filter Tags */}", c4)
c6 = find_line("{/* Container 6: Detected Components List / Table Container */}", c5)
grid_end = find_line("</div>", c6)

print(f"C2: {c2}")
print(f"C3: {c3}")
print(f"Cam Locks: {cam_locks}")
print(f"Board Insp: {board_insp}")
print(f"Col R: {col_r}")
print(f"C4: {c4}")
print(f"C5: {c5}")
print(f"C6: {c6}")

