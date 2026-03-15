/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
  ],
  presets: [require('nativewind/preset')],
  theme: {
    extend: {
      colors: {
        brand: {
          primary: '#2D004B',
          light: '#4A007F',
          mid: '#6B0FAD',
        },
        accent: {
          blue: '#89b4fa',
          'blue-dark': '#1a2540',
        },
        status: {
          danger: '#f38ba8',
          green: '#A6E3A1',
          yellow: '#F9E2AF',
          orange: '#FAB387',
        },
        surface: {
          primary: '#0D0A18',
          card: '#1E1A2E',
          elevated: '#3D3550',
        },
      },
    },
  },
  plugins: [],
};
