/** Inspection parameters shared by single-image inspection, test snaps and AOI scans. */
export interface InspectionParams {
  conf: number;
  matchDist: number;
  failOnExtra: boolean;
  imgsz: number;
  multiframeEnabled: boolean;
  targetFrames: number;
  passRatio: number;
}

export const DEFAULT_PARAMS: InspectionParams = {
  conf: 0.25,
  matchDist: 50,
  failOnExtra: true,
  imgsz: 1280,
  multiframeEnabled: true,
  targetFrames: 5,
  passRatio: 0.8,
};

export type SetParams = (update: Partial<InspectionParams>) => void;
