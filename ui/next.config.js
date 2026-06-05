/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  // API_BASE_URL устанавливается через env при сборке или в docker-compose.yml
  // NEXT_PUBLIC_API_BASE_URL=http://localhost:8020
  env: {
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8020',
  },
}

module.exports = nextConfig
