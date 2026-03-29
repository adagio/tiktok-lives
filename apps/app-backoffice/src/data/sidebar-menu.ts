export interface MenuItem {
  label: string;
  href: string;
  icon: "home" | "clips" | "video" | "topics" | "eye" | "user" | "calendar" | "chart" | "gift";
}

export const menuItems: MenuItem[] = [
  { label: "Inicio", href: "/", icon: "home" },
  { label: "Dias", href: "/dias", icon: "calendar" },
  { label: "Sesiones", href: "/sesiones", icon: "video" },
  { label: "Stats", href: "/stats", icon: "chart" },
  { label: "Clips", href: "/clips", icon: "clips" },
  { label: "Topics", href: "/topics", icon: "topics" },
  { label: "Donadores", href: "/donadores", icon: "gift" },
  { label: "Autores", href: "/autores", icon: "user" },
  { label: "Vigilados", href: "/vigilados", icon: "eye" },
];
