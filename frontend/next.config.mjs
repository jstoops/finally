/** @type {import('next').NextConfig} */
const isDev = process.env.NODE_ENV === "development";

const nextConfig = {
  output: "export",
  trailingSlash: false,
  images: { unoptimized: true },
  // Rewrites are ignored by static export; only the dev server proxies /api to FastAPI.
  ...(isDev && {
    async rewrites() {
      return [{ source: "/api/:path*", destination: "http://localhost:8000/api/:path*" }];
    },
  }),
};

export default nextConfig;
