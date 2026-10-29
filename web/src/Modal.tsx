import { useEffect, useRef } from "react";
import type { KeyboardEventHandler, ReactNode } from "react";
import { Icon } from "./shared";
export function Modal({
  title,
  onClose,
  children,
  wide = false,
  onKeyDown,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  onKeyDown?: KeyboardEventHandler<HTMLDialogElement>;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const node = ref.current!;
    const focused = document.activeElement as HTMLElement | null;
    node.showModal();
    return () => {
      node.close();
      focused?.focus({ preventScroll: true });
    };
  }, []);
  return (
    <dialog
      className={"inspector" + (wide ? " inspector-wide" : "")}
      ref={ref}
      aria-labelledby="dialog-title"
      onKeyDown={onKeyDown}
      onCancel={() => close.current()}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          const r = e.currentTarget.getBoundingClientRect();
          if (
            e.clientX < r.left ||
            e.clientX > r.right ||
            e.clientY < r.top ||
            e.clientY > r.bottom
          )
            close.current();
        }
      }}
    >
      <header className="inspector-header">
        <h2 id="dialog-title">{title}</h2>
        <button
          className="reel-icon"
          aria-label="Close review"
          onClick={() => close.current()}
        >
          <Icon name="close" />
        </button>
      </header>
      {children}
    </dialog>
  );
}
