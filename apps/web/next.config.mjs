/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    typedRoutes: true,
  },
  // Allow imports from the workspace tokens package (CSS only)
  transpilePackages: ["@dsim/ui-tokens"],
};

export default nextConfig;
