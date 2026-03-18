export interface MenuItem {
  label: string;
  href: string;
  icon: "home" | "clips" | "video" | "topics" | "eye";
}

export const menuItems: MenuItem[] = [
  { label: "Inicio", href: "/", icon: "home" },
  { label: "Sesiones", href: "/sesiones", icon: "video" },
  { label: "Clips", href: "/clips", icon: "clips" },
  { label: "Topics", href: "/topics", icon: "topics" },
  { label: "Vigilados", href: "/vigilados", icon: "eye" },
];
