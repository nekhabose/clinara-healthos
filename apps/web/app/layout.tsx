import type { ReactNode } from "react";

export const metadata = {
  title: "Clinara HealthOS",
  description: "Governed clinical workflow intelligence",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
