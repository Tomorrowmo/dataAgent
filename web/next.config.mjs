/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Note: `output: 'standalone'` was dropped because Next 15's CSS pipeline
  // emits zero stylesheets under standalone mode for our setup. The container
  // image is slightly larger as a result (~250 MB instead of ~150 MB) but the
  // page actually has CSS, which beats the alternative.
  async rewrites() {
    const apiBase = process.env.API_PROXY_TARGET || 'http://127.0.0.1:8077';
    return [{ source: '/api/:path*', destination: `${apiBase}/api/:path*` }];
  },
};

export default nextConfig;
