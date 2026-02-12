import { cn } from "../../lib/utils";

const variants: Record<string, string> = {
  default: "bg-gray-100 text-gray-800",
  active: "bg-blue-100 text-blue-800",
  running: "bg-blue-100 text-blue-800",
  pending: "bg-yellow-100 text-yellow-800",
  awaiting_approval: "bg-amber-100 text-amber-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
};

interface BadgeProps {
  variant?: string;
  children: React.ReactNode;
  className?: string;
}

export function Badge({ variant = "default", children, className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        variants[variant] ?? variants.default,
        className,
      )}
    >
      {children}
    </span>
  );
}
