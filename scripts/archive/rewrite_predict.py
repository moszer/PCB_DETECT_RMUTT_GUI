with open("/Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/PCB Electronic components/training-dashboard/components/PredictPanel.tsx", "r") as f:
    lines = f.readlines()

def get(start, end):
    return lines[start:end+1]

def find_line(s, start=0, end=None):
    if end is None: end = len(lines)
    for i in range(start, end):
        if s in lines[i]:
            return i
    return -1

main_return = find_line("  return (")

c1_start = find_line("{/* ── Container 1: Top Header Bar ── */}", main_return)
grid_start = find_line('<div className="grid grid-cols-1 lg:grid-cols-12', c1_start)

left_col_start = find_line('<div className="lg:col-span-4', grid_start)
c2_start = find_line("{/* Container 2: Model & Thresholds Card */}", left_col_start)
cam_locks_start = find_line("<CameraLocks", c2_start)
board_insp_start = find_line("<BoardInspection", cam_locks_start)
c3_start = find_line("{/* Container 3: Source Card", board_insp_start)
right_col_start = find_line('{/* ── Right Column', c3_start)

c4_start = find_line("{/* Container 4: Main Visualizer Card */}", right_col_start)
c5_start = find_line("{/* Container 5: KPI Summary Metrics Bar & Filter Tags */}", c4_start)
c6_start = find_line("{/* Container 6: Detected Components List / Table Container */}", c5_start)
grid_end = find_line("</div>", find_line("</div>", c6_start) + 10) # wait, better search backwards from end

end_div = find_line("    </div>", c6_start)
while "  );" not in lines[end_div+1] and "  );" not in lines[end_div+2]:
    end_div = find_line("    </div>", end_div+1)

# Extraction
c1 = get(c1_start, grid_start - 1)
c2 = get(c2_start, cam_locks_start - 2) # excluding wrapper divs if any?
# Wait, cam_locks is wrapped in `{inputMode === "camera" && <CameraLocks.../>}`
cam_locks_idx = find_line("{inputMode === \"camera\" && <CameraLocks", c2_start)
c2 = get(c2_start, cam_locks_idx - 1)
cam_locks = get(cam_locks_idx, cam_locks_idx)
board_insp_idx = find_line("<BoardInspection", cam_locks_idx)
board_insp = get(board_insp_idx, board_insp_idx)

c3 = get(c3_start, right_col_start - 3) # Up to the end of left column

c4 = get(c4_start, c5_start - 1)
c5 = get(c5_start, c6_start - 1)

# The end of C6 is before the end of Right Column, which is before the end of the Grid.
c6 = get(c6_start, end_div - 2) # roughly. Let's just find the closing div of C6.
# C6 starts at `<div className="flex flex-col rounded-2xl bg-[#141619]/95`
c6_div = find_line('<div', c6_start)
# We can just take everything from c6_start to end_div - 2
c6 = get(c6_start, end_div - 2)

new_jsx = []
new_jsx.append('    <div className="flex flex-col gap-4 sm:gap-6 pb-12 w-full max-w-full overflow-hidden">\n')
new_jsx.extend(c1)
new_jsx.append('      {/* Main Grid Wrapper */}\n')
new_jsx.append('      <div className="grid grid-cols-1 lg:grid-cols-12 xl:grid-cols-12 gap-4 sm:gap-6 items-start">\n')

new_jsx.append('        {/* LEFT COLUMN: Setup & Settings (3 cols) */}\n')
new_jsx.append('        <div className="lg:col-span-4 xl:col-span-3 flex flex-col gap-4 sm:gap-6">\n')
new_jsx.extend(c2)
new_jsx.extend(cam_locks)
new_jsx.extend(c3)
new_jsx.append('        </div>\n\n')

new_jsx.append('        {/* CENTER COLUMN: Main Visualizer & KPI (6 cols) */}\n')
new_jsx.append('        <div className="lg:col-span-8 xl:col-span-6 flex flex-col gap-4 sm:gap-6 min-w-0">\n')
new_jsx.extend(c4)
new_jsx.extend(c5)
new_jsx.append('        </div>\n\n')

new_jsx.append('        {/* RIGHT COLUMN: Inspection & Results (3 cols) */}\n')
new_jsx.append('        <div className="lg:col-span-12 xl:col-span-3 flex flex-col gap-4 sm:gap-6 min-w-0">\n')
new_jsx.extend(board_insp)
new_jsx.extend(c6)
new_jsx.append('        </div>\n')

new_jsx.append('      </div>\n')
new_jsx.append('    </div>\n')
new_jsx.append('  );\n')

out = lines[:main_return] + new_jsx + lines[end_div+2:]

with open("/Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/PCB Electronic components/training-dashboard/components/PredictPanel.tsx", "w") as f:
    f.writelines(out)
print("Done")
