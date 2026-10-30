export class ReelCamera {
  constructor(
    viewport: HTMLElement,
    track: HTMLElement,
    onPosition: (position: number, zoom: number) => void,
  );
  x: number;
  y: number;
  zoom: number;
  targetZoom: number;
  width: number;
  height: number;
  trackWidth: number;
  trackHeight: number;
  min: number;
  max: number;
  centerEdges?: boolean;
  onResize?: () => void;
  bounds(): void;
  measure(): void;
  jump(x: number, y?: number): void;
  go(x: number, velocity?: number, y?: number, velocityY?: number): void;
  zoomTo(value: number, x?: number, y?: number, direct?: boolean): void;
  fit(): void;
  reveal(index: number, width: number, force?: boolean): void;
  destroy(): void;
}
