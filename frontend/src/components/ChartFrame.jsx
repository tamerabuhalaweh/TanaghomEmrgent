import React, { useEffect, useRef, useState } from "react";

export default function ChartFrame({ className = "h-64", children }) {
  const ref = useRef(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;

    const update = () => {
      const rect = node.getBoundingClientRect();
      setSize({
        width: Math.max(0, Math.floor(rect.width)),
        height: Math.max(0, Math.floor(rect.height)),
      });
    };

    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const ready = size.width > 0 && size.height > 0;

  return (
    <div ref={ref} className={`${className} min-w-0`}>
      {ready
        ? React.cloneElement(React.Children.only(children), {
            width: size.width,
            height: size.height,
          })
        : null}
    </div>
  );
}
