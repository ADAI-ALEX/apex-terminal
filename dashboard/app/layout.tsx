import type { Metadata } from "next";
import "reactflow/dist/style.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Apex Algo",
  description: "Real-time monitoring for the Apex spread-betting algorithm.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        {/* Apply the saved theme before paint to avoid a flash. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{var m=localStorage.getItem('apex.theme')||'dark';var e=m;if(m==='auto'){var h=new Date().getHours();e=(h>=7&&h<19)?'light':'dark';}if(e==='light')document.documentElement.classList.add('theme-light');}catch(e){}",
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
