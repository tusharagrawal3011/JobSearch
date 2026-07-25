import "./globals.css";
import Nav from "./components/Nav";

export const metadata = {
  title: "Job Application Agent",
  description: "Local dashboard for the Job Application Agent system",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <div className="layout">
          <Nav />
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
