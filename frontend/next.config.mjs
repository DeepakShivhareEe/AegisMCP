/** @type {import('next').NextConfig} */
const backendOrigin = (process.env.BACKEND_ORIGIN || "http://localhost:8000").replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  experimental: {
    optimizePackageImports: ['lucide-react'],
  },
  // Serve the API through the frontend origin in production. Browsers block
  // third-party cookies (SameSite=None) across *.vercel.app -> *.onrender.com,
  // which would silently drop the session cookie; proxying keeps auth,
  // CSRF and SSE first-party. No effect locally, where the client calls the
  // backend directly via NEXT_PUBLIC_API_URL.
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backendOrigin}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
