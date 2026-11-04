export type VerticalMotion = {offsetY: number; velocityY: number};

export function startJump(motion: VerticalMotion): boolean {
  if (motion.offsetY < 0 || motion.velocityY !== 0) return false;
  motion.offsetY = -0.01;
  motion.velocityY = -390;
  return true;
}

export function advanceVertical(motion: VerticalMotion, delta: number): void {
  if (motion.offsetY < 0 || motion.velocityY < 0) {
    motion.velocityY += 980 * delta;
    motion.offsetY += motion.velocityY * delta;
  }
  if (motion.offsetY >= 0) {
    motion.offsetY = 0;
    motion.velocityY = 0;
  }
}
