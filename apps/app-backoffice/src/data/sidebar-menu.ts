export interface MenuItem {
  label: string;
  href: string;
  icon: "home" | "clips" | "video" | "topics";
}

export const menuItems: MenuItem[] = [
  { label: "Inicio", href: "/", icon: "home" },
  { label: "Sesiones", href: "/sesiones", icon: "video" },
  { label: "Clips", href: "/clips", icon: "clips" },
  { label: "Topics", href: "/topics", icon: "topics" },
];
