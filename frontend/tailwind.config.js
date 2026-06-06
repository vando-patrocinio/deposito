/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ["./src/**/*.{js,jsx,ts,tsx}", "./public/index.html"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      colors: {
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        card: { DEFAULT: 'hsl(var(--card))', foreground: 'hsl(var(--card-foreground))' },
        popover: { DEFAULT: 'hsl(var(--popover))', foreground: 'hsl(var(--popover-foreground))' },
        primary: { DEFAULT: 'hsl(var(--primary))', foreground: 'hsl(var(--primary-foreground))' },
        secondary: { DEFAULT: 'hsl(var(--secondary))', foreground: 'hsl(var(--secondary-foreground))' },
        muted: { DEFAULT: 'hsl(var(--muted))', foreground: 'hsl(var(--muted-foreground))' },
        accent: { DEFAULT: 'hsl(var(--accent))', foreground: 'hsl(var(--accent-foreground))' },
        destructive: { DEFAULT: 'hsl(var(--destructive))', foreground: 'hsl(var(--destructive-foreground))' },
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        // iter215ac — Institutional palette (manual 2026-06)
        // Cores semânticas que consomem CSS variables — IDs descritivos
        // pra deixar fácil migrar `text-slate-700` → `text-ink` etc.
        brand: {
          DEFAULT: 'var(--brand-primary)',
          hover: 'var(--brand-primary-hover)',
          soft: 'var(--accent-soft)',
          'soft-fg': 'var(--accent-soft-fg)',
        },
        brand2: {
          DEFAULT: 'var(--secondary)',
          hover: 'var(--secondary-hover)',
          soft: 'var(--secondary-soft)',
          'soft-fg': 'var(--secondary-soft-fg)',
        },
        ink: {
          DEFAULT: 'var(--text-primary)',
          secondary: 'var(--text-secondary)',
          muted: 'var(--text-muted)',
        },
        surface: {
          DEFAULT: 'var(--bg-surface)',
          alt: 'var(--bg-surface-2)',
          muted: 'var(--bg-muted)',
          app: 'var(--bg-app)',
        },
        success: {
          DEFAULT: 'var(--success)',
          soft: 'var(--success-soft)',
          'soft-fg': 'var(--success-soft-fg)',
        },
        warning: {
          DEFAULT: 'var(--warning)',
          soft: 'var(--warning-soft)',
          'soft-fg': 'var(--warning-soft-fg)',
        },
        danger: {
          DEFAULT: 'var(--danger)',
          soft: 'var(--danger-soft)',
          'soft-fg': 'var(--danger-soft-fg)',
        },
        info: {
          DEFAULT: 'var(--info)',
          soft: 'var(--info-soft)',
          'soft-fg': 'var(--info-soft-fg)',
        },
        chart: {
          '1': 'hsl(var(--chart-1))', '2': 'hsl(var(--chart-2))',
          '3': 'hsl(var(--chart-3))', '4': 'hsl(var(--chart-4))',
          '5': 'hsl(var(--chart-5))',
        },
      },
      boxShadow: {
        'xs': 'var(--shadow-xs)',
        'sm': 'var(--shadow-sm)',
        'md': 'var(--shadow-md)',
        'lg': 'var(--shadow-lg)',
        'brand': 'var(--shadow-brand)',
      },
      keyframes: {
        'accordion-down': { from: { height: '0' }, to: { height: 'var(--radix-accordion-content-height)' } },
        'accordion-up': { from: { height: 'var(--radix-accordion-content-height)' }, to: { height: '0' } },
        'fade-in': { from: { opacity: '0', transform: 'translateY(4px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
        'fade-in': 'fade-in 240ms ease-out',
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
