import type { Metadata } from "next";
import { MotionConfig } from "motion/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

export const metadata: Metadata = {
  title: "Divya",
  description: "India-first market intelligence terminal",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased">
        {/*
          Space UI's reduced-motion handling is NOT automatic -- it has to be opted into.
          A terminal that animates a data grid while someone is reading numbers is the exact
          opposite of a precision instrument, so this is a correctness requirement here, not
          a polish item.
        */}
        <MotionConfig reducedMotion="user">
          <TooltipProvider>{children}</TooltipProvider>
        </MotionConfig>
      </body>
    </html>
  );
}
