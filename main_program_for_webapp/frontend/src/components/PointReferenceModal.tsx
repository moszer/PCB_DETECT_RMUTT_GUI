"use client";

import BoardInspection from "./BoardInspection";
import type { CustomPointRequest } from "@/types";
import type { ExpectedComponent } from "@/lib/board-inspection";
import type { InspectionParams } from "@/lib/params";
import { formatMm } from "@/lib/format";
import { Modal } from "./ui";

interface Props {
  point: CustomPointRequest;
  pointIndex: number;
  params: InspectionParams;
  onClose: () => void;
  onSave: (pointIndex: number, image: string, items: ExpectedComponent[]) => void;
  onMoveToPoint?: () => Promise<void>;
}

export default function PointReferenceModal({ point, pointIndex, params, onClose, onSave, onMoveToPoint }: Props) {
  return (
    <Modal
      open
      onClose={onClose}
      size="xl"
      title={`ต้นแบบจุดที่ ${pointIndex + 1} · ${point.name ?? ""}`}
      subtitle={`X ${formatMm(point.x_mm)} · Y ${formatMm(point.y_mm)} mm · ซูม ${point.zoom || 1}×`}
    >
      <BoardInspection
        key={`${point.id}:${pointIndex}`}
        point={point}
        params={params}
        onMoveToPoint={onMoveToPoint}
        onSave={(image, items) => {
          onSave(pointIndex, image, items);
          onClose();
        }}
      />
    </Modal>
  );
}
