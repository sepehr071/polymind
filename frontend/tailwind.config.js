/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
  	extend: {
  		colors: {
  			background: {
  				DEFAULT: 'hsl(var(--background))',
  				secondary: 'hsl(var(--background-secondary))',
  				tertiary: 'hsl(var(--background-tertiary))',
  				elevated: 'hsl(var(--background-elevated))'
  			},
  			foreground: {
  				DEFAULT: 'hsl(var(--foreground))',
  				secondary: 'hsl(var(--foreground-secondary))',
  				tertiary: 'hsl(var(--foreground-tertiary))'
  			},
  			border: {
  				DEFAULT: 'hsl(var(--border))',
  				light: 'hsl(var(--border-light))',
  				strong: 'hsl(var(--border-strong))'
  			},
  			accent: {
  				DEFAULT: 'hsl(var(--accent))',
  				hover: 'hsl(var(--accent-hover))',
  				muted: 'hsl(var(--accent-muted))',
  				foreground: 'hsl(var(--accent-foreground))'
  			},
  			success: 'rgb(var(--success) / <alpha-value>)',
  			warning: 'rgb(var(--warning) / <alpha-value>)',
  			error: 'rgb(var(--error) / <alpha-value>)',
  			card: {
  				DEFAULT: 'hsl(var(--card))',
  				foreground: 'hsl(var(--card-foreground))'
  			},
  			popover: {
  				DEFAULT: 'hsl(var(--popover))',
  				foreground: 'hsl(var(--popover-foreground))'
  			},
  			primary: {
  				DEFAULT: 'hsl(var(--primary))',
  				foreground: 'hsl(var(--primary-foreground))',
  				dark: 'hsl(var(--primary-dark))'
  			},
  			secondary: {
  				DEFAULT: 'hsl(var(--secondary))',
  				foreground: 'hsl(var(--secondary-foreground))'
  			},
  			muted: {
  				DEFAULT: 'hsl(var(--muted))',
  				foreground: 'hsl(var(--muted-foreground))'
  			},
  			destructive: {
  				DEFAULT: 'hsl(var(--destructive))',
  				foreground: 'hsl(var(--destructive-foreground))'
  			},
  			input: 'hsl(var(--input))',
  			ring: 'hsl(var(--ring))',
  			'bg-0': 'hsl(var(--bg-0))',
  			'bg-1': 'hsl(var(--bg-1))',
  			'bg-2': 'hsl(var(--bg-2))',
  			'bg-3': 'hsl(var(--bg-3))',
  			'bg-4': 'hsl(var(--bg-4))',
  			'line': 'hsl(var(--line))',
  			'line-2': 'hsl(var(--line-2))',
  			'line-3': 'hsl(var(--line-3))',
  			'fg-0': 'hsl(var(--fg-0))',
  			'fg-1': 'hsl(var(--fg-1))',
  			'fg-2': 'hsl(var(--fg-2))',
  			'fg-3': 'hsl(var(--fg-3))',
  			'fg-4': 'hsl(var(--fg-4))',
  			ok: 'hsl(var(--ok) / <alpha-value>)',
  			warn: 'hsl(var(--warn) / <alpha-value>)',
  			err: 'hsl(var(--err) / <alpha-value>)',
  			violet: 'hsl(var(--violet) / <alpha-value>)',
  			pink: 'hsl(var(--pink) / <alpha-value>)',
  			teal: 'hsl(var(--teal) / <alpha-value>)',
  			'role-owner-bg': 'hsl(var(--role-owner-bg))',
  			'role-owner-fg': 'hsl(var(--role-owner-fg))',
  			'role-owner-line': 'hsl(var(--role-owner-line))',
  			'role-editor-bg': 'hsl(var(--role-editor-bg))',
  			'role-editor-fg': 'hsl(var(--role-editor-fg))',
  			'role-editor-line': 'hsl(var(--role-editor-line))',
  			'role-viewer-bg': 'hsl(var(--role-viewer-bg))',
  			'role-viewer-fg': 'hsl(var(--role-viewer-fg))',
  			'role-viewer-line': 'hsl(var(--role-viewer-line))'
  		},
  		fontFamily: {
  			sans: [
  				'Vazirmatn',
  				'ui-sans-serif',
  				'system-ui',
  				'-apple-system',
  				'sans-serif'
  			],
  			display: [
  				'Vazirmatn',
  				'ui-sans-serif',
  				'system-ui',
  				'sans-serif'
  			],
  			mono: [
  				'Geist Mono',
  				'JetBrains Mono',
  				'Fira Code',
  				'monospace'
  			],
  			persian: [
  				'Vazirmatn',
  				'ui-sans-serif',
  				'system-ui',
  				'sans-serif'
  			]
  		},
  		boxShadow: {
  			elevated: '0 4px 12px var(--shadow-color)',
  			dropdown: '0 8px 24px var(--shadow-color)',
  			'sm': 'var(--shadow-sm)',
  			'md': 'var(--shadow-md)',
  			'lg': 'var(--shadow-lg)',
  			'glow-accent': 'var(--shadow-glow-accent)',
  			'primary-glow': '0 10px 25px -5px hsl(var(--primary) / 0.20)',
  			'primary-glow-lg': '0 12px 28px -4px hsl(var(--primary) / 0.30)',
  		},
  		animation: {
  			'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
  			'fade-in': 'fadeIn 0.2s ease-out',
  			'slide-up': 'slideUp 0.3s ease-out',
  			'slide-in-left': 'slideInLeft 0.3s ease-out',
  			'slide-in-right': 'slideInRight 0.3s ease-out',
  			'slide-in-bottom': 'slideInBottom 0.3s ease-out',
  			'accordion-down': 'accordion-down 0.2s ease-out',
  			'accordion-up': 'accordion-up 0.2s ease-out',
  			'toast-in': 'toastIn 220ms cubic-bezier(0.22, 1, 0.36, 1) both',
  			'toast-out': 'toastOut 140ms cubic-bezier(0.4, 0, 1, 1) both'
  		},
  		keyframes: {
  			fadeIn: {
  				'0%': {
  					opacity: '0'
  				},
  				'100%': {
  					opacity: '1'
  				}
  			},
  			slideUp: {
  				'0%': {
  					opacity: '0',
  					transform: 'translateY(10px)'
  				},
  				'100%': {
  					opacity: '1',
  					transform: 'translateY(0)'
  				}
  			},
  			slideInLeft: {
  				'0%': {
  					opacity: '0',
  					transform: 'translateX(-100%)'
  				},
  				'100%': {
  					opacity: '1',
  					transform: 'translateX(0)'
  				}
  			},
  			slideInRight: {
  				'0%': {
  					opacity: '0',
  					transform: 'translateX(100%)'
  				},
  				'100%': {
  					opacity: '1',
  					transform: 'translateX(0)'
  				}
  			},
  			slideInBottom: {
  				'0%': {
  					opacity: '0',
  					transform: 'translateY(100%)'
  				},
  				'100%': {
  					opacity: '1',
  					transform: 'translateY(0)'
  				}
  			},
  			'accordion-down': {
  				from: {
  					height: '0'
  				},
  				to: {
  					height: 'var(--radix-accordion-content-height)'
  				}
  			},
  			'accordion-up': {
  				from: {
  					height: 'var(--radix-accordion-content-height)'
  				},
  				to: {
  					height: '0'
  				}
  			},
  			toastIn: {
  				'0%': {
  					opacity: '0',
  					transform: 'translateY(-8px) scale(0.96)'
  				},
  				'100%': {
  					opacity: '1',
  					transform: 'translateY(0) scale(1)'
  				}
  			},
  			toastOut: {
  				'0%': {
  					opacity: '1',
  					transform: 'translateY(0) scale(1)'
  				},
  				'100%': {
  					opacity: '0',
  					transform: 'translateY(-4px) scale(0.98)'
  				}
  			}
  		},
  		borderRadius: {
  			lg: 'var(--radius)',
  			md: 'calc(var(--radius) - 2px)',
  			sm: 'calc(var(--radius) - 4px)'
  		}
  	}
  },
  plugins: [require("tailwindcss-animate")],
}
