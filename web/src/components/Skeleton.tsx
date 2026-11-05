export function Skeleton({ height = 96 }: { height?: number }) {
  return <div className="skeleton card" style={{ height }} aria-hidden="true" />;
}
