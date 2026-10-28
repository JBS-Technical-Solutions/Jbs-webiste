export const site = {
  name: "JBS Technical Solutions",
  tagline: "Intelligence behind the process",
  url: "https://jbstechservices.com",
  address: "Greater Houston, Texas",
  linkedin: "https://www.linkedin.com/company/jbs-technical-solutions/",
};

export type NavItem = {
  href: string;
  label: string;
  /** Full page load — used for apps served outside the main Next.js app (e.g. HAZOP Studio). */
  external?: boolean;
};

export const nav: NavItem[] = [
  { href: "/about", label: "About" },
  { href: "/digital-twins", label: "Digital Twins" },
  { href: "/hazop", label: "HAZOP", external: true },
];

export const contactHref = "/contact";
export const contactLabel = "Contact Us";

export const stats = [
  { value: "2021", label: "Founded in Greater Houston" },
  { value: "4", label: "Core capabilities" },
  { value: "5", label: "Energy & chemical sectors served" },
];
