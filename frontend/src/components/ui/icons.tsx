import type { SVGProps } from "react";

/**
 * 线性图标（24 栅格、1.8 线宽、圆头）。只收舞台上真正用到的几枚，不引图标库。
 * 一律 aria-hidden：图标不承担语义，可读名由所在按钮的 aria-label 给。
 */
function Icon({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      width="1em"
      height="1em"
      {...props}
    >
      {children}
    </svg>
  );
}

export function SpeakerIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M11 5 6 9H3v6h3l5 4V5Z" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7" />
      <path d="M18.5 5.5a9.5 9.5 0 0 1 0 13" />
    </Icon>
  );
}

export function SpeakerOffIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M11 5 6 9H3v6h3l5 4V5Z" />
      <path d="m16 9.5 5 5" />
      <path d="m21 9.5-5 5" />
    </Icon>
  );
}

export function StopIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <rect x="6.5" y="6.5" width="11" height="11" rx="2" />
    </Icon>
  );
}

export function MicIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5.5 11a6.5 6.5 0 0 0 13 0" />
      <path d="M12 17.5V21" />
    </Icon>
  );
}

export function RewindIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M4 5v5h5" />
      <path d="M4.5 14a8 8 0 1 0 1.9-8.4L4 10" />
    </Icon>
  );
}

export function ScrollIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M7 4h11a2 2 0 0 1 2 2v1h-4" />
      <path d="M16 7v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-1h10v1" />
      <path d="M7 4a2 2 0 0 0-2 2v11" />
      <path d="M9 9h4M9 12.5h4" />
    </Icon>
  );
}

export function SparkleIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M12 3.5 13.8 9a2 2 0 0 0 1.2 1.2l5.5 1.8-5.5 1.8a2 2 0 0 0-1.2 1.2L12 20.5 10.2 15a2 2 0 0 0-1.2-1.2L3.5 12 9 10.2A2 2 0 0 0 10.2 9L12 3.5Z" />
    </Icon>
  );
}

export function CloseIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="m6 6 12 12" />
      <path d="M18 6 6 18" />
    </Icon>
  );
}

export function SendIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M4 12 20 4l-5.5 16-3-6.5L4 12Z" />
      <path d="m11.5 13.5 3.5-3.5" />
    </Icon>
  );
}
