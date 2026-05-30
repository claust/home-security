import { useLayoutEffect, useRef, useState } from "react";

/**
 * Thin React wrapper around Observable Plot with a responsive width.
 *
 * Plot renders to a detached DOM node, so we mount it imperatively. We measure
 * synchronously on layout (falling back to the parent's width, since an empty
 * container can briefly report 0) and re-measure on both ResizeObserver and
 * window-resize events, feeding the width back into `render` so charts
 * re-layout crisply instead of being CSS-scaled.
 */
export function PlotFigure({
  render,
  className,
}: {
  render: (width: number) => HTMLElement | SVGSVGElement;
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => {
      const next = Math.floor(el.clientWidth || el.parentElement?.clientWidth || 0);
      setWidth((prev) => (next > 0 && next !== prev ? next : prev));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    if (el.parentElement) observer.observe(el.parentElement);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el || width === 0) return;
    const figure = render(width);
    el.append(figure);
    return () => figure.remove();
  }, [render, width]);

  return <div ref={containerRef} className={className} style={{ width: "100%" }} />;
}
