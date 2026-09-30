with open("frontend/src/components/AOIScanView.tsx", "r") as f:
    lines = f.readlines()

def find_line(s, start=0):
    for i in range(start, len(lines)):
        if s in lines[i]:
            return i
    return -1

def get(start, end):
    return lines[start:end+1]

stage_conn_start = find_line("{/* Stage Connection Card */}")
camera_src_start = find_line("{/* Camera Source Selector Card */}")
stage_pos_start = find_line("{/* Stage Position & Jog Controls */}")
scan_plan_start = find_line("{/* Scan Planner Setup (Custom Target Points & Zoom) */}")
scan_trigger_start = find_line("{/* Scan Trigger Buttons */}")
main_monitor = find_line("{/* 2. Main Scan Monitor Area */}")

prog_strip_start = find_line("{/* Progress & Live Status Strip */}")
prog_strip_end = find_line("{/* Center View Switcher Tabs */}") - 2

split_idx = find_line("{/* 1. Split View: Live Camera + Scan Points Grid (Default & Active during Scan) */}")
lcf_start = find_line("<LiveCameraFeed", split_idx)
lcf_end = find_line("onRefresh={refreshCameras}", lcf_start) + 1 # includes the /> line

grid_start = find_line("{/* Grid Cards Container */}")
grid_end = find_line("{/* 2. Full Live Camera Viewport */}") - 3

modal_start = find_line("{/* Point Detail Modal */}")
return_start = find_line("return (")
end_start = len(lines) - 2

# Extraction
stage_conn = get(stage_conn_start, camera_src_start - 1)
camera_src = get(camera_src_start, stage_pos_start - 1)
stage_pos = get(stage_pos_start, scan_plan_start - 1)
prog_strip = get(prog_strip_start, prog_strip_end)
lcf = get(lcf_start, lcf_end)
for i in range(len(lcf)):
    if 'className=' in lcf[i]:
        lcf[i] = '                className="w-full h-full min-h-[440px]"\n'
        break
scan_plan = get(scan_plan_start, scan_trigger_start - 1)
scan_trigger = get(scan_trigger_start, main_monitor - 2)
grid = get(grid_start, grid_end)
modal = get(modal_start, end_start - 1)

new_jsx = []
new_jsx.append('    <div className="flex flex-col xl:flex-row h-[calc(100vh-85px)] bg-slate-950 text-slate-100 overflow-hidden">\n')

# Left Panel
new_jsx.append('      {/* 1. Left Panel (Hardware) */}\n')
new_jsx.append('      <div className="w-full xl:w-[320px] bg-slate-900 border-r border-slate-800 p-4 flex flex-col gap-4 overflow-y-auto shrink-0">\n')
new_jsx.extend(stage_conn)
new_jsx.extend(camera_src)
new_jsx.extend(stage_pos)
new_jsx.append('      </div>\n\n')

# Center Panel
new_jsx.append('      {/* 2. Center Panel (Camera) */}\n')
new_jsx.append('      <div className="flex-1 flex flex-col p-4 overflow-hidden gap-4 min-w-0 bg-slate-950">\n')
new_jsx.append('        {/* Progress & Live Status Strip */}\n')
new_jsx.append('        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 flex flex-wrap items-center justify-between gap-4">\n')
new_jsx.extend(prog_strip)
new_jsx.append('        </div>\n\n')

new_jsx.append('        {/* Main Camera View */}\n')
new_jsx.append('        <div className="flex-1 min-h-[460px] rounded-xl bg-slate-900 border border-slate-800 p-2 overflow-hidden relative shadow-xl">\n')
new_jsx.extend(lcf)
new_jsx.append('        </div>\n')
new_jsx.append('      </div>\n\n')

# Right Panel
new_jsx.append('      {/* 3. Right Panel (Plan & Results) */}\n')
new_jsx.append('      <div className="w-full xl:w-[420px] bg-slate-900 border-l border-slate-800 p-4 flex flex-col gap-4 overflow-y-auto shrink-0">\n')
new_jsx.extend(scan_plan)
new_jsx.extend(scan_trigger)

new_jsx.append('        {/* Results Grid */}\n')
new_jsx.append('        <div className="flex-1 flex flex-col min-h-[350px] rounded-xl bg-slate-900 border border-slate-800 p-3 overflow-hidden shadow-xl mt-2">\n')
new_jsx.append('          <div className="flex items-center justify-between mb-2.5 pb-2 border-b border-slate-800">\n')
new_jsx.append('            <div className="flex items-center gap-2">\n')
new_jsx.append('              <Layers className="w-4 h-4 text-blue-400" />\n')
new_jsx.append('              <span className="text-xs font-bold text-slate-200">\n')
new_jsx.append('                Inspected Points ({results.length} / {totalScanPoints})\n')
new_jsx.append('              </span>\n')
new_jsx.append('            </div>\n')
new_jsx.append('            {activeScanReport?.overall_verdict && (\n')
new_jsx.append('              <span\n')
new_jsx.append('                className={`px-2.5 py-0.5 rounded-full text-[11px] font-bold ${\n')
new_jsx.append('                  activeScanReport.overall_verdict === "PASS"\n')
new_jsx.append('                    ? "bg-emerald-950 text-emerald-300 border border-emerald-700"\n')
new_jsx.append('                    : activeScanReport.overall_verdict === "FAIL"\n')
new_jsx.append('                    ? "bg-red-950 text-red-300 border border-red-700"\n')
new_jsx.append('                    : "bg-amber-950 text-amber-300 border border-amber-700"\n')
new_jsx.append('                }`}\n')
new_jsx.append('              >\n')
new_jsx.append('                Verdict: {activeScanReport.overall_verdict}\n')
new_jsx.append('              </span>\n')
new_jsx.append('            )}\n')
new_jsx.append('          </div>\n')
new_jsx.extend(grid)
new_jsx.append('        </div>\n')
new_jsx.append('      </div>\n\n')

new_jsx.extend(modal)
new_jsx.append('    </div>\n')
new_jsx.append('  );\n')

out_lines = lines[:return_start+1] + new_jsx + lines[end_start:]

with open("frontend/src/components/AOIScanView.tsx", "w") as f:
    f.writelines(out_lines)

print("Rewrote layout reliably!")
