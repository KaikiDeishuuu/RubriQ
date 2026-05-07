/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#08111f',
          900: '#101b2d',
          800: '#18253d',
          700: '#243653',
        },
        paper: '#f6f1e8',
        parchment: '#fffaf0',
        gold: {
          50: '#fff9e6',
          100: '#fdf1be',
          200: '#f6de7c',
          300: '#e8c95a',
        },
        sage: {
          50: '#edf6f1',
          100: '#d7eadf',
          200: '#b5d9c7',
          300: '#86b89f',
          400: '#57866f',
        },
        slateBlue: {
          50: '#edf3ff',
          100: '#d9e3fb',
          200: '#b2c4f4',
          300: '#7d98e6',
          400: '#4f6dd4',
          500: '#3149b2',
        },
      },
      fontFamily: {
        display: ['"Cormorant Garamond"', 'Iowan Old Style', 'Palatino Linotype', 'serif'],
        body: ['"Source Sans 3"', 'Avenir Next', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      boxShadow: {
        soft: '0 18px 50px rgba(8, 17, 31, 0.10)',
        lift: '0 12px 28px rgba(8, 17, 31, 0.14)',
      },
      backgroundImage: {
        'page-texture': 'radial-gradient(circle at top left, rgba(49, 73, 178, 0.12), transparent 35%), radial-gradient(circle at top right, rgba(103, 128, 64, 0.12), transparent 30%), linear-gradient(180deg, rgba(255,255,255,0.6), rgba(255,255,255,0.0))',
      },
    },
  },
  plugins: [],
}
