"""
Consolidated database seeding script (SQLAlchemy / Postgres edition).

Seeds prompt templates (32) and workflow templates (23: 15 general + 8
social-media). Phase 6 cutover replaced the Mongo writes with ORM inserts.

Usage:
    python scripts/seed.py                 # Seed everything
    python scripts/seed.py --workflows     # Only workflow templates
    python scripts/seed.py --prompts       # Only prompt templates
    python scripts/seed.py --no-clear      # Don't clear existing data first
"""
import argparse
import copy
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

# Load env BEFORE importing the app so Config picks up real values.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, '.env'), override=True)
sys.path.insert(0, ROOT)

# =============================================================================
# PROMPT TEMPLATES DATA (32 templates across 8 categories)
# =============================================================================
PROMPT_TEMPLATES = [
    # Product Photography
    {'name': 'Clean White Background - Product Shot', 'category': 'product_photography', 'template_text': 'Clean product shot of {{product}} on pure white background (RGB 255,255,255), professional studio lighting, soft even illumination from 45-degree angle, subtle fill light, no harsh shadows, product fills 85% of frame, sharp focus, high resolution, clean minimalist aesthetic', 'variables': ['product'], 'description': 'Professional e-commerce product photo with clean white background'},
    {'name': 'Premium Product Photography', 'category': 'product_photography', 'template_text': 'High-end product photography of {{product}}, luxurious presentation, dramatic lighting with soft shadows, premium aesthetic, professional studio setup, detailed texture visible, elegant composition, commercial photography style, 4K quality', 'variables': ['product'], 'description': 'Luxury product shot with premium feel'},
    {'name': 'Product with Lifestyle Context', 'category': 'product_photography', 'template_text': 'Product photo of {{product}} in real-world setting, natural environment, authentic lifestyle context, warm natural lighting, professional composition, genuine atmosphere, aspirational yet relatable, high-quality photography', 'variables': ['product'], 'description': 'Product shown in context of use'},
    {'name': 'Detailed Close-Up Shot', 'category': 'product_photography', 'template_text': 'Extreme close-up of {{product}}, macro photography, intricate details visible, texture emphasis, professional lighting to highlight features, shallow depth of field, high resolution, product detail showcase', 'variables': ['product'], 'description': 'Macro shot highlighting product details'},

    # Advertisement
    {'name': 'Modern Advertisement', 'category': 'advertisement', 'template_text': 'Professional advertisement photo of {{subject}}, modern aesthetic, vibrant colors, dramatic lighting, clean background, commercial photography style, high-end marketing campaign look, eye-catching composition, 4K quality', 'variables': ['subject'], 'description': 'Modern, eye-catching advertisement photo'},
    {'name': 'Luxury Brand Campaign', 'category': 'advertisement', 'template_text': 'Luxury advertisement for {{brand_product}}, premium aesthetic, sophisticated composition, elegant lighting, high-end fashion photography style, aspirational mood, refined color palette, professional commercial photography', 'variables': ['brand_product'], 'description': 'High-end luxury brand advertising'},
    {'name': 'Dynamic Action Shot', 'category': 'advertisement', 'template_text': '{{subject}} in dynamic action, energetic composition, motion blur effect, vibrant colors, dramatic lighting, professional sports photography style, high impact visual, advertising campaign quality', 'variables': ['subject'], 'description': 'Energetic action-focused advertisement'},
    {'name': 'Minimalist Brand Ad', 'category': 'advertisement', 'template_text': 'Minimalist advertisement featuring {{product}}, clean simple composition, negative space, modern design, subtle colors, professional minimalist photography, brand-focused aesthetic, contemporary style', 'variables': ['product'], 'description': 'Clean, minimalist advertising approach'},

    # Social Media
    {'name': 'Instagram-Optimized Post', 'category': 'social_media', 'template_text': 'Eye-catching Instagram post image for {{topic}}, 1:1 square composition, bold vibrant colors, engaging visual elements, modern design, professional yet approachable style, high engagement potential', 'variables': ['topic'], 'description': 'Square format optimized for Instagram'},
    {'name': 'LinkedIn Professional', 'category': 'social_media', 'template_text': 'Professional LinkedIn post image about {{topic}}, authoritative yet approachable, clean modern design, business-appropriate colors, professional photography style, corporate aesthetic, trustworthy feel', 'variables': ['topic'], 'description': 'Professional business-focused content'},
    {'name': 'Pinterest-Style Vertical', 'category': 'social_media', 'template_text': 'Vertical Pinterest-optimized image for {{topic}}, 2:3 aspect ratio, inspiring composition, beautiful aesthetics, aspirational feel, high quality photography, pin-worthy design', 'variables': ['topic'], 'description': 'Tall format for Pinterest'},
    {'name': 'Story/Reel Vertical', 'category': 'social_media', 'template_text': 'Vertical story image about {{topic}}, 9:16 format, mobile-optimized composition, bold text-friendly design, engaging visual, modern aesthetic, social media native feel', 'variables': ['topic'], 'description': 'Vertical format for Stories and Reels'},

    # Lifestyle
    {'name': 'Authentic Lifestyle Moment', 'category': 'lifestyle', 'template_text': 'Lifestyle photo showing {{subject}} in use, natural environment, authentic moment, warm natural lighting, genuine emotion, aspirational setting, professional photography, real-life context', 'variables': ['subject'], 'description': 'Natural, authentic lifestyle photography'},
    {'name': 'Home Interior Lifestyle', 'category': 'lifestyle', 'template_text': '{{subject}} in beautiful home interior, cozy atmosphere, natural window light, modern decor, lived-in feel, warm inviting ambiance, interior design photography style, aspirational yet attainable', 'variables': ['subject'], 'description': 'Home setting lifestyle shot'},
    {'name': 'Outdoor Lifestyle', 'category': 'lifestyle', 'template_text': '{{subject}} in outdoor natural setting, golden hour lighting, scenic background, candid moment, nature photography style, fresh outdoor atmosphere, authentic lifestyle', 'variables': ['subject'], 'description': 'Outdoor natural environment lifestyle'},
    {'name': 'Urban Lifestyle', 'category': 'lifestyle', 'template_text': '{{subject}} in modern urban environment, city background, contemporary lifestyle, natural street photography style, authentic urban moment, modern metropolitan feel', 'variables': ['subject'], 'description': 'Urban city lifestyle photography'},

    # Hero/Banner
    {'name': 'Cinematic Hero Banner', 'category': 'hero_banner', 'template_text': 'Wide cinematic hero image for {{purpose}}, dramatic composition, professional lighting, high contrast, premium aesthetic, landscape orientation 16:9, ultra high quality, visually striking, banner-ready', 'variables': ['purpose'], 'description': 'Dramatic wide banner image'},
    {'name': 'Website Hero Section', 'category': 'hero_banner', 'template_text': 'Professional website hero image representing {{concept}}, modern web design aesthetic, clean composition, ample negative space for text overlay, professional photography, brand-friendly, high resolution 16:9', 'variables': ['concept'], 'description': 'Website header/hero section image'},
    {'name': 'Email Header Banner', 'category': 'hero_banner', 'template_text': 'Email newsletter header image for {{topic}}, wide format, attention-grabbing, professional design, brand cohesive, clear focal point, marketing email optimized', 'variables': ['topic'], 'description': 'Email campaign header image'},
    {'name': 'Landing Page Hero', 'category': 'hero_banner', 'template_text': 'Conversion-focused landing page hero image for {{product_service}}, clear value proposition visual, professional photography, trust-building aesthetic, high quality, attention-grabbing', 'variables': ['product_service'], 'description': 'Landing page conversion-focused hero'},

    # Tech/SaaS
    {'name': 'SaaS Dashboard Visualization', 'category': 'tech_saas', 'template_text': 'Modern tech visualization representing {{concept}}, clean minimal design, gradient background in {{colors}}, 3D elements, futuristic aesthetic, professional B2B marketing style, digital innovation feel', 'variables': ['concept', 'colors'], 'description': 'Tech/SaaS product visualization'},
    {'name': 'Abstract Tech Concept', 'category': 'tech_saas', 'template_text': 'Abstract digital illustration of {{technology_concept}}, geometric shapes, modern color palette, clean minimal style, technology-forward aesthetic, professional tech marketing', 'variables': ['technology_concept'], 'description': 'Abstract technology concept illustration'},
    {'name': 'Cloud/Network Visualization', 'category': 'tech_saas', 'template_text': 'Professional visualization of {{cloud_concept}}, interconnected nodes, network diagram style, modern tech aesthetic, blue and white color scheme, enterprise software marketing style', 'variables': ['cloud_concept'], 'description': 'Cloud computing/network visualization'},
    {'name': 'AI/Data Visualization', 'category': 'tech_saas', 'template_text': 'Futuristic AI and data visualization showing {{data_concept}}, neural network style, glowing elements, dark background, modern tech aesthetic, artificial intelligence theme', 'variables': ['data_concept'], 'description': 'AI and data-focused visualization'},

    # Food/Restaurant
    {'name': 'Overhead Food Photography', 'category': 'food_restaurant', 'template_text': 'Appetizing food photography of {{dish}}, overhead flat-lay angle, natural daylight, fresh ingredients visible, garnished beautifully, restaurant-quality presentation, vibrant colors, professional food styling', 'variables': ['dish'], 'description': 'Top-down food photography'},
    {'name': 'Close-Up Food Detail', 'category': 'food_restaurant', 'template_text': 'Mouth-watering close-up of {{dish}}, detailed texture visible, steam rising, professional food photography, warm appetizing lighting, restaurant menu quality, culinary art presentation', 'variables': ['dish'], 'description': 'Detailed close-up food shot'},
    {'name': 'Restaurant Ambiance', 'category': 'food_restaurant', 'template_text': '{{dish}} served in elegant restaurant setting, ambient lighting, table setting visible, fine dining atmosphere, professional restaurant photography, upscale presentation, atmospheric mood', 'variables': ['dish'], 'description': 'Food with restaurant atmosphere'},
    {'name': 'Rustic Food Styling', 'category': 'food_restaurant', 'template_text': '{{dish}} with rustic presentation, wooden table surface, natural ingredients around, warm natural lighting, artisanal feel, home-cooked aesthetic, food blog style photography', 'variables': ['dish'], 'description': 'Rustic, artisanal food presentation'},

    # Fashion/Apparel
    {'name': 'Fashion Product Shot', 'category': 'fashion_apparel', 'template_text': 'Fashion product photo of {{item}}, professional model wearing {{item}}, studio lighting, clean background, high-fashion editorial style, detailed fabric texture visible, e-commerce ready', 'variables': ['item'], 'description': 'Professional fashion product photography'},
    {'name': 'Editorial Fashion', 'category': 'fashion_apparel', 'template_text': 'High-fashion editorial photo featuring {{clothing_item}}, dramatic lighting, artistic composition, professional fashion photography, vogue-style aesthetic, striking pose, premium fashion magazine quality', 'variables': ['clothing_item'], 'description': 'Editorial fashion magazine style'},
    {'name': 'Lifestyle Fashion', 'category': 'fashion_apparel', 'template_text': 'Lifestyle fashion photo of person wearing {{outfit}}, natural environment, candid moment, street style photography, authentic fashion, real-world context, modern casual aesthetic', 'variables': ['outfit'], 'description': 'Casual lifestyle fashion photography'},
    {'name': 'Flat Lay Apparel', 'category': 'fashion_apparel', 'template_text': 'Flat lay fashion photo of {{clothing_items}}, overhead view, styled arrangement, clean background, professional product photography, e-commerce optimized, clothing details visible', 'variables': ['clothing_items'], 'description': 'Overhead flat lay of clothing'},

    # --- Company / professional templates ---
    {'name': 'Data Visualization Infographic', 'category': 'infographic', 'template_text': 'Professional vertical infographic visualizing {{topic}}, clean flat design, bar and pie charts, statistic cards with bold numbers, modern line icons, {{colors}} color palette, generous whitespace, clear visual hierarchy, corporate aesthetic, text-safe layout, high resolution', 'variables': ['topic', 'colors'], 'description': 'Data-driven infographic with charts, stat cards and clean flat icons'},
    {'name': 'Comparison Infographic', 'category': 'infographic', 'template_text': 'Comparison infographic contrasting {{option_a}} versus {{option_b}}, clean two-column layout, icons and key statistics, checkmarks and metrics, professional corporate style, balanced color blocks, easy-to-scan structured grid, high resolution', 'variables': ['option_a', 'option_b'], 'description': 'Side-by-side two-column comparison with icons and metrics'},
    {'name': 'Process Steps Infographic', 'category': 'infographic', 'template_text': 'Step-by-step process infographic explaining {{process}}, numbered horizontal flow with connecting arrows, minimal flat icon per step, {{colors}} accent palette, clean modern layout, professional business style, ample whitespace, presentation-ready', 'variables': ['process', 'colors'], 'description': 'Numbered step-by-step flow for how-to or onboarding processes'},
    {'name': 'Timeline Infographic', 'category': 'infographic', 'template_text': 'Company timeline infographic mapping {{topic}} from {{start}} to {{end}}, horizontal milestone markers, year labels, concise event icons, clean teal and slate aesthetic, professional corporate design, balanced spacing, presentation-ready, high resolution', 'variables': ['topic', 'start', 'end'], 'description': 'Horizontal milestone timeline for company history or roadmaps'},
    {'name': 'SaaS Hero Banner', 'category': 'software_promo', 'template_text': 'Wide website hero banner for a {{product_category}} SaaS product, soft blue-to-purple gradient background, floating abstract 3D shapes, subtle glassmorphism UI card accents, polished studio lighting, premium modern tech mood, clean text-safe negative space for headline and CTA, crisp edges, high-resolution marketing design, 16:9', 'variables': ['product_category'], 'description': 'Wide landing-page hero with 3D shapes, glassmorphism and CTA space'},
    {'name': 'Feature Announcement', 'category': 'software_promo', 'template_text': 'Feature announcement graphic for {{feature}} in a software product, clean tech aesthetic, light gradient background, illustrative icon representing the feature, modern sans-serif headline space, professional B2B SaaS style, vibrant accent color, social-ready', 'variables': ['feature'], 'description': 'Announce a new software feature with a clean B2B tech look'},
    {'name': 'App Dashboard Mockup', 'category': 'software_promo', 'template_text': 'Sleek product mockup showcasing a {{app_type}} dashboard on a floating device frame, modern UI screens, soft shadows, gradient studio background in {{colors}}, glassmorphism panels, premium tech marketing style, high resolution', 'variables': ['app_type', 'colors'], 'description': 'Floating device frame showing your app or dashboard UI'},
    {'name': 'Product Launch Creative', 'category': 'software_promo', 'template_text': 'Eye-catching product launch creative for {{product}}, bold introducing-style composition, dramatic lighting, dark navy background with bright accent glow, floating 3D geometric shapes, premium tech aesthetic, clear focal point, high-end campaign look, high resolution', 'variables': ['product'], 'description': 'Dramatic introducing-style launch creative on dark navy with accent glow'},
    {'name': 'LinkedIn Post', 'category': 'corporate', 'template_text': 'Professional LinkedIn post image about {{topic}}, authoritative yet approachable, clean modern corporate design, business-appropriate {{colors}} palette, subtle geometric accents, professional photography style, trustworthy feel, text-safe space, square 1:1', 'variables': ['topic', 'colors'], 'description': 'Authoritative square graphic for LinkedIn thought-leadership posts'},
    {'name': 'Report Cover', 'category': 'corporate', 'template_text': 'Corporate report cover design for {{title}}, elegant minimal layout, refined typography space, abstract data-inspired background graphics, professional navy and gold palette, premium business aesthetic, clean grid, A4 portrait, high resolution', 'variables': ['title'], 'description': 'Elegant whitepaper or annual-report cover, A4 portrait'},
    {'name': 'Company Announcement', 'category': 'corporate', 'template_text': 'Corporate announcement banner for {{announcement}}, clean professional design, brand-forward layout, modern flat illustration, {{colors}} corporate palette, confident headline space, business-appropriate, polished, web-ready', 'variables': ['announcement', 'colors'], 'description': 'Polished banner for company news and announcements'},
    {'name': 'Webinar Banner', 'category': 'corporate', 'template_text': 'Professional webinar banner for {{event_topic}}, modern corporate design, speaker-photo placeholder area, date and title text-safe zones, gradient background in {{colors}}, clean tech-business aesthetic, 16:9 presentation format, high resolution', 'variables': ['event_topic', 'colors'], 'description': 'Webinar or conference banner with speaker-photo and title zones, 16:9'},
    {'name': 'Title Slide Background', 'category': 'presentation', 'template_text': 'Clean presentation title slide background for {{topic}}, minimal professional design, abstract geometric accents in {{colors}}, generous text-safe negative space, modern corporate aesthetic, subtle gradient, 16:9 widescreen, high resolution', 'variables': ['topic', 'colors'], 'description': 'Minimal 16:9 title-slide background with text-safe space'},
    {'name': 'Section Divider Slide', 'category': 'presentation', 'template_text': 'Presentation section divider slide for {{section}}, bold minimal layout, large headline space, single accent shape, {{colors}} palette, clean corporate style, balanced composition, 16:9 widescreen', 'variables': ['section', 'colors'], 'description': 'Bold 16:9 section-divider slide background'},
    {'name': 'Pitch Deck Background', 'category': 'presentation', 'template_text': 'Modern pitch deck slide background for a {{industry}} startup, sleek minimal design, subtle abstract tech motifs, dark mode with neon accent in {{colors}}, ample text-safe area, premium investor-ready aesthetic, 16:9', 'variables': ['industry', 'colors'], 'description': 'Sleek dark-mode pitch-deck background, investor-ready, 16:9'},
]

# =============================================================================
# WORKFLOW TEMPLATES DATA (15 templates)
# =============================================================================
WORKFLOW_TEMPLATES = [
    # 1. Product Photography Studio
    {
        'name': 'Product Photography Studio',
        'description': 'Professional e-commerce product shot on clean white background with studio lighting',
        'nodes': [
            {
                'id': 'upload-product-1',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 150},
                'data': {
                    'label': 'Upload Product Image',
                    'imageUrl': None
                }
            },
            {
                'id': 'gen-studio-1',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 150},
                'data': {
                    'label': 'Studio Shot',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Professional product photography of the uploaded item, pure white seamless background, soft studio lighting from multiple angles, high-end commercial quality, sharp focus on product details, centered composition, 8K resolution, photorealistic, advertising quality',
                    'negativePrompt': 'harsh shadows, reflections, colored background, blur, watermark, text, logos, hands, people, cluttered',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-upload-studio',
                'source': 'upload-product-1',
                'target': 'gen-studio-1',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 2. Lifestyle Scene Generator
    {
        'name': 'Lifestyle Scene Generator',
        'description': 'Generate your product in 3 different real-world contexts: kitchen, office, and outdoor cafe',
        'nodes': [
            {
                'id': 'upload-product-2',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 300},
                'data': {
                    'label': 'Upload Product Image',
                    'imageUrl': None
                }
            },
            {
                'id': 'gen-kitchen-2',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 0},
                'data': {
                    'label': 'Kitchen Scene',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Product placed elegantly in a modern minimalist Scandinavian kitchen, natural morning light streaming through large window, white marble countertop, lifestyle photography, warm inviting tones, bokeh background, editorial style, magazine cover quality',
                    'negativePrompt': 'cluttered, dark, low quality, artificial lighting, stock photo feel, people, hands',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-office-2',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 300},
                'data': {
                    'label': 'Office Scene',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Product on a sleek modern office desk, professional workspace environment, MacBook laptop nearby, green plants, natural daylight from window, clean minimalist aesthetic, productivity lifestyle, premium quality photography',
                    'negativePrompt': 'cluttered desk, messy, dark, low quality, artificial, stock photo feel, people',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-cafe-2',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 600},
                'data': {
                    'label': 'Outdoor Cafe Scene',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Product in outdoor European cafe setting, rustic wooden table, beautifully blurred background with greenery and flowers, golden hour warm lighting, lifestyle shot, cozy atmosphere, Instagram worthy, travel aesthetic',
                    'negativePrompt': 'cluttered, dark, low quality, artificial, stock photo feel, indoor, people, hands',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-kitchen',
                'source': 'upload-product-2',
                'target': 'gen-kitchen-2',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-office',
                'source': 'upload-product-2',
                'target': 'gen-office-2',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-cafe',
                'source': 'upload-product-2',
                'target': 'gen-cafe-2',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 3. Social Media Content Pack
    {
        'name': 'Social Media Content Pack',
        'description': 'Generate product shots optimized for Instagram, Stories, and Website banners',
        'nodes': [
            {
                'id': 'upload-product-3',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 300},
                'data': {
                    'label': 'Upload Product Image',
                    'imageUrl': None
                }
            },
            {
                'id': 'gen-instagram-3',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 0},
                'data': {
                    'label': 'Instagram Square',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Eye-catching product shot for Instagram feed, vibrant saturated colors, clean soft gradient background in pastel tones, modern aesthetic, perfect square composition 1:1 ratio, trending style, high engagement visual, professional product photography',
                    'negativePrompt': 'dull colors, cluttered, text, watermark, blurry, low quality',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-story-3',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 300},
                'data': {
                    'label': 'Story/Reel Format',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Vertical product showcase for Instagram Stories and TikTok, dynamic interesting angle, bold vibrant colors, ample negative space at top and bottom for text overlay, social media ready, Gen-Z aesthetic, trendy, 9:16 vertical composition',
                    'negativePrompt': 'horizontal, cluttered, no space for text, boring angle, dull',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-banner-3',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 600},
                'data': {
                    'label': 'Website Banner',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Wide horizontal product banner for website hero section, product positioned on left third with clean negative space on right for headline text, professional marketing material, clean modern design, subtle gradient background, panoramic 3:1 ratio',
                    'negativePrompt': 'centered product, no space for text, cluttered, vertical, busy background',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-instagram',
                'source': 'upload-product-3',
                'target': 'gen-instagram-3',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-story',
                'source': 'upload-product-3',
                'target': 'gen-story-3',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-banner',
                'source': 'upload-product-3',
                'target': 'gen-banner-3',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 4. Seasonal Campaign Creator
    {
        'name': 'Seasonal Campaign Creator',
        'description': 'Generate holiday-themed and summer-themed product shots for seasonal marketing',
        'nodes': [
            {
                'id': 'upload-product-4',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 150},
                'data': {
                    'label': 'Upload Product Image',
                    'imageUrl': None
                }
            },
            {
                'id': 'gen-holiday-4',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 0},
                'data': {
                    'label': 'Holiday Theme',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Product in festive Christmas holiday setting, elegant gift presentation, warm cozy fireplace lighting, pine branches and holly decorations, gold and deep red accents, twinkling fairy lights bokeh, gift-worthy luxurious presentation, seasonal marketing, winter wonderland feel',
                    'negativePrompt': 'dark gloomy, cluttered, summer elements, beach, cheap looking, low quality',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-summer-4',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 300},
                'data': {
                    'label': 'Summer Vibes',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Product in bright tropical summer setting, beach vacation vibes, palm leaves and monstera plants, bright sunshine with lens flare, fresh vibrant colors, turquoise and coral accents, vacation mood, poolside aesthetic, refreshing summer marketing campaign',
                    'negativePrompt': 'dark, gloomy, winter, snow, Christmas, cold colors, indoor, low quality',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-holiday',
                'source': 'upload-product-4',
                'target': 'gen-holiday-4',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-summer',
                'source': 'upload-product-4',
                'target': 'gen-summer-4',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 5. Brand Style Transfer
    {
        'name': 'Brand Style Transfer',
        'description': 'Apply a reference image style to your product for consistent brand aesthetic',
        'nodes': [
            {
                'id': 'upload-style-5',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 0},
                'data': {
                    'label': 'Upload Style Reference',
                    'imageUrl': None
                }
            },
            {
                'id': 'upload-product-5',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 220},
                'data': {
                    'label': 'Upload Product Image',
                    'imageUrl': None
                }
            },
            {
                'id': 'gen-styled-5',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 100},
                'data': {
                    'label': 'Styled Product',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Product photo beautifully styled to match the aesthetic, color palette, lighting mood, and visual style of the reference image, maintaining perfect brand consistency, professional quality, cohesive visual identity, same photographic style and tone',
                    'negativePrompt': 'inconsistent style, clashing colors, generic look, different mood, mismatched aesthetic',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-style-ref',
                'source': 'upload-style-5',
                'target': 'gen-styled-5',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-product-styled',
                'source': 'upload-product-5',
                'target': 'gen-styled-5',
                'sourceHandle': 'output',
                'targetHandle': 'input-1'
            }
        ]
    },

    # 6. Before/After Enhancement
    {
        'name': 'Photo Enhancement',
        'description': 'Transform a basic product photo into professional commercial-quality imagery',
        'nodes': [
            {
                'id': 'upload-basic-6',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 150},
                'data': {
                    'label': 'Upload Basic Photo',
                    'imageUrl': None
                }
            },
            {
                'id': 'gen-enhanced-6',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 150},
                'data': {
                    'label': 'Enhanced Professional',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Transform into stunning professional product photography, perfect studio lighting setup, clean pure background, remove all imperfections and distractions, commercial advertising quality, high-end retouching, magazine-worthy, color corrected, sharp details, premium look',
                    'negativePrompt': 'original flaws, poor lighting, amateur look, blur, noise, artifacts, cluttered background, shadows',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-enhance',
                'source': 'upload-basic-6',
                'target': 'gen-enhanced-6',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 7. Advertisement Creator
    {
        'name': 'Advertisement Creator',
        'description': 'Generate A/B test ad variations: minimalist Apple-style vs bold energetic design',
        'nodes': [
            {
                'id': 'upload-product-7',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 150},
                'data': {
                    'label': 'Upload Product Image',
                    'imageUrl': None
                }
            },
            {
                'id': 'gen-minimal-7',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 0},
                'data': {
                    'label': 'Minimalist Ad',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Minimalist luxury advertisement, product elegantly floating on clean soft gray gradient background, subtle natural shadow beneath, premium Apple-style aesthetic, lots of white space, sophisticated understated elegance, high-end brand feel, clean typography ready',
                    'negativePrompt': 'busy, cluttered, colorful, loud, cheap looking, harsh shadows, text',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-bold-7',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 300},
                'data': {
                    'label': 'Bold Energetic Ad',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Bold dynamic advertisement design, product with vibrant colorful gradient background in electric blue and hot pink, energetic diagonal composition, motion blur accents, attention-grabbing eye-catching, modern Gen-Z marketing visual, sale promotion ready, high impact',
                    'negativePrompt': 'boring, static, muted colors, plain white, minimal, subtle, corporate boring',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-minimal',
                'source': 'upload-product-7',
                'target': 'gen-minimal-7',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-bold',
                'source': 'upload-product-7',
                'target': 'gen-bold-7',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 8. Character Variation Generator
    {
        'name': 'Character Variation Generator',
        'description': 'Create different poses and expressions for your character or mascot design',
        'nodes': [
            {
                'id': 'upload-character-8',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 150},
                'data': {
                    'label': 'Upload Character/Mascot',
                    'imageUrl': None
                }
            },
            {
                'id': 'gen-action-8',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 0},
                'data': {
                    'label': 'Action Pose',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Same character in dynamic action pose, running or jumping with movement and energy, exactly consistent style colors and design as reference, character design sheet style, full body visible, clean white background, mascot illustration, maintaining all character features',
                    'negativePrompt': 'different character, wrong colors, inconsistent style, static boring pose, cropped',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-happy-8',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 300},
                'data': {
                    'label': 'Happy Expression',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Same character with joyful happy excited expression, big smile, sparkling eyes, celebratory pose with arms up, exactly consistent design style and colors as reference, expressive face, mascot style, clean white background, maintaining all character features',
                    'negativePrompt': 'different character, wrong colors, inconsistent style, sad, neutral, angry',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-action',
                'source': 'upload-character-8',
                'target': 'gen-action-8',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-happy',
                'source': 'upload-character-8',
                'target': 'gen-happy-8',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 9. Character Turnaround Reference Sheet
    {
        'name': 'Character Turnaround Reference Sheet',
        'description': 'Generate consistent multi-angle character views for game dev, animation, and 3D modeling reference sheets',
        'nodes': [
            {
                'id': 'upload-character-9',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 300},
                'data': {
                    'label': 'Upload Character Design',
                    'imageUrl': None
                }
            },
            {
                'id': 'gen-front-9',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 0},
                'data': {
                    'label': 'Front View (0°)',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Character turnaround sheet, FRONT VIEW facing camera directly, full body visible head to toe, T-pose or neutral standing pose, exactly matching the reference character design colors style and proportions, clean white background, character design reference sheet style, consistent lighting from front, professional concept art quality, game development asset',
                    'negativePrompt': 'different character, wrong colors, side view, back view, cropped, partial body, different style, inconsistent design',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-side-9',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 200},
                'data': {
                    'label': 'Side View (90°)',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Character turnaround sheet, SIDE VIEW profile facing right, full body visible head to toe, neutral standing pose, exactly matching the reference character design colors style and proportions, clean white background, character design reference sheet style, consistent lighting, professional concept art quality, game development asset, perfect profile silhouette',
                    'negativePrompt': 'different character, wrong colors, front view, back view, cropped, partial body, different style, facing left, 3/4 angle',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-back-9',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 400},
                'data': {
                    'label': 'Back View (180°)',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Character turnaround sheet, BACK VIEW from behind, full body visible head to toe, neutral standing pose, exactly matching the reference character design colors style and proportions, clean white background, character design reference sheet style, showing back details of costume and hair, professional concept art quality, game development asset',
                    'negativePrompt': 'different character, wrong colors, front view, side view, cropped, partial body, different style, face visible',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-threequarter-9',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 600},
                'data': {
                    'label': '3/4 View (45°)',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Character turnaround sheet, THREE-QUARTER VIEW at 45 degree angle, full body visible head to toe, dynamic but readable pose, exactly matching the reference character design colors style and proportions, clean white background, character design reference sheet style, showing depth and dimension, professional concept art quality, game development asset',
                    'negativePrompt': 'different character, wrong colors, front view, side view, back view, cropped, partial body, different style',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-front-9',
                'source': 'upload-character-9',
                'target': 'gen-front-9',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-side-9',
                'source': 'upload-character-9',
                'target': 'gen-side-9',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-back-9',
                'source': 'upload-character-9',
                'target': 'gen-back-9',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-threequarter-9',
                'source': 'upload-character-9',
                'target': 'gen-threequarter-9',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 10. Two-Pass Enhancement Pipeline
    {
        'name': 'Two-Pass Enhancement Pipeline',
        'description': 'Progressive 3-stage refinement: background cleanup -> lighting correction -> final polish. Professional multi-pass workflow.',
        'nodes': [
            {
                'id': 'upload-raw-10',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 150},
                'data': {
                    'label': 'Upload Raw Photo',
                    'imageUrl': None
                }
            },
            {
                'id': 'gen-pass1-10',
                'type': 'imageGen',
                'position': {'x': 350, 'y': 150},
                'data': {
                    'label': 'Pass 1: Background Cleanup',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Clean up the background of this product photo, remove all distracting elements and clutter, replace with clean neutral gradient background, keep the product exactly as is with all details preserved, professional product photography background isolation, seamless edge blending',
                    'negativePrompt': 'change product, alter product colors, blur product, crop product, different product angle',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-pass2-10',
                'type': 'imageGen',
                'position': {'x': 650, 'y': 150},
                'data': {
                    'label': 'Pass 2: Lighting Correction',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Enhance the lighting of this product photo, add professional studio lighting setup with soft key light and fill light, remove harsh shadows, add subtle rim lighting for product separation, correct color temperature to neutral daylight, maintain all product details and colors exactly',
                    'negativePrompt': 'change product, alter product design, harsh shadows, overexposed, underexposed, color cast',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-pass3-10',
                'type': 'imageGen',
                'position': {'x': 950, 'y': 150},
                'data': {
                    'label': 'Pass 3: Final Polish',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Final professional polish pass, enhance sharpness and micro-details, add subtle reflection on surface beneath product, perfect color grading for commercial use, magazine-quality final result, 8K ultra sharp details, advertising campaign ready, high-end retouching finish',
                    'negativePrompt': 'blur, noise, artifacts, over-sharpened, unnatural colors, plastic look',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-pass1-10',
                'source': 'upload-raw-10',
                'target': 'gen-pass1-10',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-pass2-10',
                'source': 'gen-pass1-10',
                'target': 'gen-pass2-10',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-pass3-10',
                'source': 'gen-pass2-10',
                'target': 'gen-pass3-10',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 11. Multi-Product Composite Scene
    {
        'name': 'Multi-Product Composite Scene',
        'description': 'Combine multiple products with a style reference into one cohesive lifestyle scene. Uses all 3 input slots.',
        'nodes': [
            {
                'id': 'upload-product-a-11',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 0},
                'data': {
                    'label': 'Upload Product A (Main)',
                    'imageUrl': None
                }
            },
            {
                'id': 'upload-product-b-11',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 200},
                'data': {
                    'label': 'Upload Product B (Secondary)',
                    'imageUrl': None
                }
            },
            {
                'id': 'upload-style-11',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 400},
                'data': {
                    'label': 'Upload Scene Style Reference',
                    'imageUrl': None
                }
            },
            {
                'id': 'gen-composite-11',
                'type': 'imageGen',
                'position': {'x': 450, 'y': 180},
                'data': {
                    'label': 'Composite Lifestyle Scene',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Create a beautiful lifestyle scene combining both products naturally, Product A as the main focus in foreground, Product B as complementary element, match the aesthetic mood lighting and style of the reference image exactly, cohesive color palette, professional product photography, natural arrangement that tells a story, editorial quality composition',
                    'negativePrompt': 'products floating, unnatural placement, mismatched styles, cluttered, cheap looking, inconsistent lighting between products',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-product-a-11',
                'source': 'upload-product-a-11',
                'target': 'gen-composite-11',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-product-b-11',
                'source': 'upload-product-b-11',
                'target': 'gen-composite-11',
                'sourceHandle': 'output',
                'targetHandle': 'input-1'
            },
            {
                'id': 'e-style-11',
                'source': 'upload-style-11',
                'target': 'gen-composite-11',
                'sourceHandle': 'output',
                'targetHandle': 'input-2'
            }
        ]
    },

    # 12. Brand Campaign Suite
    {
        'name': 'Brand Campaign Suite',
        'description': 'Complete marketing campaign: style-match your product, then generate Hero Banner, Social Square, and Print Ad variants. Most complex template.',
        'nodes': [
            {
                'id': 'upload-product-12',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 100},
                'data': {
                    'label': 'Upload Product Image',
                    'imageUrl': None
                }
            },
            {
                'id': 'upload-brand-12',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 320},
                'data': {
                    'label': 'Upload Brand Style Guide',
                    'imageUrl': None
                }
            },
            {
                'id': 'gen-styled-base-12',
                'type': 'imageGen',
                'position': {'x': 380, 'y': 200},
                'data': {
                    'label': 'Styled Base Image',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Product photography styled to perfectly match the brand aesthetic from the reference, consistent color palette, matching lighting mood and tone, brand-appropriate background treatment, professional commercial quality, cohesive visual identity, ready for campaign adaptation',
                    'negativePrompt': 'off-brand colors, inconsistent style, generic look, mismatched aesthetic, amateur quality',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-hero-12',
                'type': 'imageGen',
                'position': {'x': 750, 'y': 0},
                'data': {
                    'label': 'Hero Banner (16:9)',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Wide cinematic hero banner composition, product positioned in left third with expansive negative space on right for headline text, dramatic brand-consistent lighting, premium advertising quality, website hero section ready, 16:9 widescreen aspect ratio, impactful visual hierarchy',
                    'negativePrompt': 'centered product, no text space, cluttered, vertical composition, busy background',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-social-12',
                'type': 'imageGen',
                'position': {'x': 750, 'y': 220},
                'data': {
                    'label': 'Social Square (1:1)',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Instagram-optimized square composition 1:1 ratio, product as bold central focus, eye-catching scroll-stopping visual, vibrant brand colors, clean modern aesthetic, social media engagement optimized, trending visual style, shareable quality',
                    'negativePrompt': 'boring, dull colors, off-center awkwardly, text overlay, watermarks',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-print-12',
                'type': 'imageGen',
                'position': {'x': 750, 'y': 440},
                'data': {
                    'label': 'Print Ad (4:5)',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Print advertisement layout 4:5 vertical ratio, product elegantly positioned in upper portion, generous space below for copy and call-to-action, magazine advertisement quality, CMYK-friendly colors, high resolution print-ready, sophisticated layout for premium publications',
                    'negativePrompt': 'no space for text, horizontal, web-only colors, low resolution feel, cluttered layout',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-product-12',
                'source': 'upload-product-12',
                'target': 'gen-styled-base-12',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-brand-12',
                'source': 'upload-brand-12',
                'target': 'gen-styled-base-12',
                'sourceHandle': 'output',
                'targetHandle': 'input-1'
            },
            {
                'id': 'e-hero-12',
                'source': 'gen-styled-base-12',
                'target': 'gen-hero-12',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-social-12',
                'source': 'gen-styled-base-12',
                'target': 'gen-social-12',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-print-12',
                'source': 'gen-styled-base-12',
                'target': 'gen-print-12',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 13. Product 360° Showcase
    {
        'name': 'Product 360° Showcase',
        'description': 'Generate 6 different viewing angles for e-commerce 360° product display. Largest template with 7 nodes.',
        'nodes': [
            {
                'id': 'upload-product-13',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 450},
                'data': {
                    'label': 'Upload Product Image',
                    'imageUrl': None
                }
            },
            {
                'id': 'gen-0deg-13',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 0},
                'data': {
                    'label': 'Front (0°)',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Product photograph from FRONT VIEW 0 degrees, straight-on angle facing camera directly, clean white e-commerce background, consistent studio lighting, exactly matching reference product design and colors, professional 360 spin photography style, sharp focus on all details',
                    'negativePrompt': 'different product, wrong angle, side view, angled view, colored background, shadows',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-60deg-13',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 180},
                'data': {
                    'label': 'Front-Right (60°)',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Product photograph from FRONT-RIGHT VIEW 60 degrees rotation, showing front and right side, clean white e-commerce background, consistent studio lighting matching other angles, exactly matching reference product design and colors, professional 360 spin photography style',
                    'negativePrompt': 'different product, wrong angle, front view, back view, colored background',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-120deg-13',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 360},
                'data': {
                    'label': 'Back-Right (120°)',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Product photograph from BACK-RIGHT VIEW 120 degrees rotation, showing back and right side, clean white e-commerce background, consistent studio lighting matching other angles, exactly matching reference product design and colors, professional 360 spin photography style',
                    'negativePrompt': 'different product, wrong angle, front view, colored background',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-180deg-13',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 540},
                'data': {
                    'label': 'Back (180°)',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Product photograph from BACK VIEW 180 degrees, showing back of product directly, clean white e-commerce background, consistent studio lighting matching other angles, exactly matching reference product design and colors, professional 360 spin photography style, showing back details',
                    'negativePrompt': 'different product, wrong angle, front visible, colored background',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-240deg-13',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 720},
                'data': {
                    'label': 'Back-Left (240°)',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Product photograph from BACK-LEFT VIEW 240 degrees rotation, showing back and left side, clean white e-commerce background, consistent studio lighting matching other angles, exactly matching reference product design and colors, professional 360 spin photography style',
                    'negativePrompt': 'different product, wrong angle, front view, right side, colored background',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-300deg-13',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 900},
                'data': {
                    'label': 'Front-Left (300°)',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Product photograph from FRONT-LEFT VIEW 300 degrees rotation, showing front and left side, clean white e-commerce background, consistent studio lighting matching other angles, exactly matching reference product design and colors, professional 360 spin photography style',
                    'negativePrompt': 'different product, wrong angle, back view, right side, colored background',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-0deg-13',
                'source': 'upload-product-13',
                'target': 'gen-0deg-13',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-60deg-13',
                'source': 'upload-product-13',
                'target': 'gen-60deg-13',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-120deg-13',
                'source': 'upload-product-13',
                'target': 'gen-120deg-13',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-180deg-13',
                'source': 'upload-product-13',
                'target': 'gen-180deg-13',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-240deg-13',
                'source': 'upload-product-13',
                'target': 'gen-240deg-13',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-300deg-13',
                'source': 'upload-product-13',
                'target': 'gen-300deg-13',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 14. Concept Art Evolution
    {
        'name': 'Concept Art Evolution',
        'description': 'Transform rough sketches into polished concept art through iterative refinement. Sketch -> Render -> Final Detail.',
        'nodes': [
            {
                'id': 'upload-sketch-14',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 150},
                'data': {
                    'label': 'Upload Rough Sketch',
                    'imageUrl': None
                }
            },
            {
                'id': 'gen-render-14',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 150},
                'data': {
                    'label': 'Initial Render',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Transform this rough sketch into a clean digital rendering, maintain the exact composition pose and design intent, add proper form and volume, establish base colors and values, clean linework, concept art style, professional digital painting foundation, keep all design elements from the sketch',
                    'negativePrompt': 'change design, different pose, different composition, lose sketch details, photorealistic',
                    'generatedImage': None
                }
            },
            {
                'id': 'gen-final-14',
                'type': 'imageGen',
                'position': {'x': 750, 'y': 150},
                'data': {
                    'label': 'Final Detailed Art',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Finalize this concept art with full professional detail, add rich textures materials and surface details, dramatic cinematic lighting with rim lights and atmospheric effects, color grade for visual impact, AAA game concept art quality, portfolio-ready illustration, maintain exact design from previous pass while adding polish and refinement',
                    'negativePrompt': 'change design, different character, lose details, flat lighting, amateur quality, different style',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-render-14',
                'source': 'upload-sketch-14',
                'target': 'gen-render-14',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-final-14',
                'source': 'gen-render-14',
                'target': 'gen-final-14',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # --- Social Media Manager pack (templates 16–23) ---

    # 16. Brief -> 3 IG Captions + 1:1 Image
    {
        'name': 'Brief -> 3 IG Captions + 1:1 Image',
        'description': 'From a campaign brief, generate three Instagram caption variants and a matching 1:1 hero image.',
        'category': 'social-media',
        'nodes': [
            {
                'id': 'brief-16',
                'type': 'textInput',
                'position': {'x': 50, 'y': 200},
                'data': {
                    'label': 'Campaign Brief',
                    'text': 'New oat-milk latte launch. Brand: calm, warm, artisan. Target: health-conscious millennials.',
                    'placeholder': 'Describe product, tone, and target audience...'
                }
            },
            {
                'id': 'captions-16',
                'type': 'aiAgent',
                'position': {'x': 400, 'y': 200},
                'data': {
                    'label': '3 IG Caption Variants',
                    'model': 'google/gemini-3.6-flash',
                    'systemPrompt': 'You are a senior Instagram copywriter. Given the campaign brief, write exactly 3 caption variants optimized for Instagram engagement. Each caption must include a hook sentence, body copy (2-3 sentences), a call to action, and 5-8 relevant hashtags. Separate each variant with "---". Output ONLY the captions, no labels or numbering.',
                    'user_prompt_template': '{{input}}',
                    'output': None
                }
            },
            {
                'id': 'image-16',
                'type': 'imageGen',
                'position': {'x': 400, 'y': 480},
                'data': {
                    'label': 'Hero Image (1:1)',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Square 1:1 Instagram hero image. Warm artisan coffee aesthetic, oat-milk latte in a ceramic cup on a rustic wooden table, soft morning window light, steam rising gently, shallow depth of field, muted earth tones, lifestyle photography, Instagram-ready composition.',
                    'negativePrompt': 'text overlay, watermark, dark, cluttered, artificial lighting, cold tones',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-brief-captions-16',
                'source': 'brief-16',
                'target': 'captions-16',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-brief-image-16',
                'source': 'brief-16',
                'target': 'image-16',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 17. Product Photo -> 5-Platform Copy Pack
    {
        'name': 'Product Photo -> 5-Platform Copy Pack',
        'description': 'Upload a product photo and get tailored copy for Instagram, X, LinkedIn, TikTok, and YouTube in one run.',
        'category': 'social-media',
        'nodes': [
            {
                'id': 'upload-17',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 400},
                'data': {
                    'label': 'Upload Product Photo',
                    'imageUrl': None
                }
            },
            {
                'id': 'ig-copy-17',
                'type': 'aiAgent',
                'position': {'x': 400, 'y': 0},
                'data': {
                    'label': 'Instagram Copy',
                    'model': 'google/gemini-3.6-flash',
                    'systemPrompt': 'You are an Instagram copywriter. Describe the product in the image, then write a single engaging Instagram post: a strong hook, 3-4 body sentences in a conversational aspirational tone, a CTA, and 8-10 hashtags. Output ONLY the post text.',
                    'user_prompt_template': 'Write Instagram copy for this product image.',
                    'output': None
                }
            },
            {
                'id': 'x-copy-17',
                'type': 'aiAgent',
                'position': {'x': 400, 'y': 180},
                'data': {
                    'label': 'X (Twitter) Copy',
                    'model': 'google/gemini-3.6-flash',
                    'systemPrompt': 'You are a witty X/Twitter copywriter. Write a punchy tweet about the product in the image. Max 240 characters. Include 2-3 relevant hashtags. Tone: sharp, curious, direct. Output ONLY the tweet.',
                    'user_prompt_template': 'Write X/Twitter copy for this product image.',
                    'output': None
                }
            },
            {
                'id': 'linkedin-copy-17',
                'type': 'aiAgent',
                'position': {'x': 400, 'y': 360},
                'data': {
                    'label': 'LinkedIn Copy',
                    'model': 'google/gemini-3.6-flash',
                    'systemPrompt': 'You are a LinkedIn content strategist. Write a professional post about the product in the image. Lead with a thought-provoking insight or question, then tie it to the product benefit (3-4 sentences), end with a professional CTA. Include 3-5 hashtags. Output ONLY the post.',
                    'user_prompt_template': 'Write LinkedIn copy for this product image.',
                    'output': None
                }
            },
            {
                'id': 'tiktok-copy-17',
                'type': 'aiAgent',
                'position': {'x': 400, 'y': 540},
                'data': {
                    'label': 'TikTok Caption',
                    'model': 'google/gemini-3.6-flash',
                    'systemPrompt': 'You are a TikTok content creator. Write a short TikTok video caption for the product in the image. Tone: playful, trend-aware, Gen-Z friendly. Max 150 characters + 5 trending hashtags. Output ONLY the caption.',
                    'user_prompt_template': 'Write a TikTok caption for this product image.',
                    'output': None
                }
            },
            {
                'id': 'yt-copy-17',
                'type': 'aiAgent',
                'position': {'x': 400, 'y': 720},
                'data': {
                    'label': 'YouTube Description',
                    'model': 'google/gemini-3.6-flash',
                    'systemPrompt': 'You are a YouTube SEO specialist. Write a YouTube video description for a short product showcase of the item in the image. Include a compelling first two sentences (these show as preview), then 3-4 feature highlights, a subscribe CTA, and 10 SEO tags preceded by #. Output ONLY the description.',
                    'user_prompt_template': 'Write a YouTube description for this product image.',
                    'output': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-upload-ig-17',
                'source': 'upload-17',
                'target': 'ig-copy-17',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-upload-x-17',
                'source': 'upload-17',
                'target': 'x-copy-17',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-upload-linkedin-17',
                'source': 'upload-17',
                'target': 'linkedin-copy-17',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-upload-tiktok-17',
                'source': 'upload-17',
                'target': 'tiktok-copy-17',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-upload-yt-17',
                'source': 'upload-17',
                'target': 'yt-copy-17',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 18. Brand Brief -> Weekly Content Calendar (5 posts)
    {
        'name': 'Brand Brief -> Weekly Content Calendar',
        'description': 'Turn a brand brief into a ready-to-schedule Monday–Friday caption calendar with post concepts.',
        'category': 'social-media',
        'nodes': [
            {
                'id': 'brief-18',
                'type': 'textInput',
                'position': {'x': 50, 'y': 200},
                'data': {
                    'label': 'Brand Brief',
                    'text': 'Sustainable activewear brand. Values: eco-friendly, performance, inclusivity. This week: launching recycled-fabric leggings.',
                    'placeholder': 'Brand description, current campaign, tone of voice...'
                }
            },
            {
                'id': 'calendar-18',
                'type': 'aiAgent',
                'position': {'x': 450, 'y': 200},
                'data': {
                    'label': 'Weekly Calendar (Mon–Fri)',
                    'model': 'google/gemini-3.6-flash',
                    'systemPrompt': 'You are a social media strategist. Given the brand brief, produce a 5-day Instagram content calendar (Monday through Friday). For each day output: DAY: [day name], CONCEPT: [1-sentence visual idea], CAPTION: [full ready-to-post caption with hook, body, CTA, and 6-8 hashtags]. Separate days with "---". Output ONLY the calendar.',
                    'user_prompt_template': '{{input}}',
                    'output': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-brief-calendar-18',
                'source': 'brief-18',
                'target': 'calendar-18',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 19. Image -> Hashtag + Hook Pack
    {
        'name': 'Image -> Hashtag + Hook Pack',
        'description': 'Upload any image and extract themes, hashtag clusters, and punchy hook lines for multiple platforms.',
        'category': 'social-media',
        'nodes': [
            {
                'id': 'upload-19',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 150},
                'data': {
                    'label': 'Upload Image',
                    'imageUrl': None
                }
            },
            {
                'id': 'extract-19',
                'type': 'aiAgent',
                'position': {'x': 400, 'y': 150},
                'data': {
                    'label': 'Hashtag + Hook Pack',
                    'model': 'google/gemini-3.6-flash',
                    'systemPrompt': 'You are a social media content analyst. Analyse the image and produce: 1) THEMES: list 3-5 core visual/emotional themes you observe. 2) HASHTAG CLUSTERS: provide 3 themed groups of 8-10 hashtags each (Niche, Mid-tier, Broad) suitable for Instagram. 3) HOOKS: write 5 punchy opening lines (hooks) that could start a post about this image — vary tone (curious, bold, emotional, witty, direct). Output each section with its header label.',
                    'user_prompt_template': 'Analyse this image and produce themes, hashtag clusters, and hooks.',
                    'output': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-upload-extract-19',
                'source': 'upload-19',
                'target': 'extract-19',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 20. Video Script -> 9:16 Storyboard (4 frames)
    {
        'name': 'Video Script -> 9:16 Storyboard (4 Frames)',
        'description': 'Turn a TikTok or Reels script into 4 vertical keyframe visuals for pre-production storyboarding.',
        'category': 'social-media',
        'nodes': [
            {
                'id': 'script-20',
                'type': 'textInput',
                'position': {'x': 50, 'y': 400},
                'data': {
                    'label': 'Video Script',
                    'text': 'Scene 1: Close-up of hands brewing pour-over coffee. Scene 2: Steam rising from a full cup. Scene 3: Person smiling, first sip. Scene 4: Cup on windowsill with morning light.',
                    'placeholder': 'Paste your video script or scene descriptions...'
                }
            },
            {
                'id': 'frame1-20',
                'type': 'imageGen',
                'position': {'x': 450, 'y': 0},
                'data': {
                    'label': 'Frame 1',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Storyboard keyframe 1 of 4 for a vertical 9:16 mobile-first video. Close-up of hands carefully pouring hot water over coffee grounds in a pour-over dripper, warm amber tones, cinematic shallow depth of field, natural light, artisan coffee aesthetic.',
                    'negativePrompt': 'horizontal composition, text, watermark, low quality',
                    'generatedImage': None
                }
            },
            {
                'id': 'frame2-20',
                'type': 'imageGen',
                'position': {'x': 450, 'y': 240},
                'data': {
                    'label': 'Frame 2',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Storyboard keyframe 2 of 4 for a vertical 9:16 mobile-first video. Beautiful close-up of steam curling upward from a freshly brewed cup of coffee on a wooden surface, backlit by soft window light, moody warm atmosphere, cinematic quality.',
                    'negativePrompt': 'horizontal composition, text, watermark, low quality, cold tones',
                    'generatedImage': None
                }
            },
            {
                'id': 'frame3-20',
                'type': 'imageGen',
                'position': {'x': 450, 'y': 480},
                'data': {
                    'label': 'Frame 3',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Storyboard keyframe 3 of 4 for a vertical 9:16 mobile-first video. Portrait of a young woman smiling warmly as she takes her first sip from a ceramic coffee cup, cozy cafe or home setting, natural window light, genuine candid emotion, vertical composition.',
                    'negativePrompt': 'horizontal composition, text, watermark, low quality, artificial lighting',
                    'generatedImage': None
                }
            },
            {
                'id': 'frame4-20',
                'type': 'imageGen',
                'position': {'x': 450, 'y': 720},
                'data': {
                    'label': 'Frame 4',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Storyboard keyframe 4 of 4 for a vertical 9:16 mobile-first video. Aesthetic shot of a ceramic coffee cup resting on a windowsill, golden morning sunlight streaming through, bokeh exterior background, warm peaceful mood, vertical 9:16 composition, lifestyle photography.',
                    'negativePrompt': 'horizontal composition, text, watermark, low quality, night time',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-script-frame1-20',
                'source': 'script-20',
                'target': 'frame1-20',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-script-frame2-20',
                'source': 'script-20',
                'target': 'frame2-20',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-script-frame3-20',
                'source': 'script-20',
                'target': 'frame3-20',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-script-frame4-20',
                'source': 'script-20',
                'target': 'frame4-20',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 21. Long-form Caption -> Repurposed across 4 Platforms
    {
        'name': 'Long Caption -> 4-Platform Repurpose',
        'description': 'Paste one long caption and auto-rewrite it to fit Instagram, X, LinkedIn, and TikTok tone and length.',
        'category': 'social-media',
        'nodes': [
            {
                'id': 'caption-21',
                'type': 'textInput',
                'position': {'x': 50, 'y': 400},
                'data': {
                    'label': 'Original Long Caption',
                    'text': 'After three years of building this brand from my kitchen table, today we finally launched our first product to the world. It feels surreal. Every late night, every rejection, every moment of doubt led to this. Thank you to every single person who believed in us before there was anything to believe in.',
                    'placeholder': 'Paste your long-form caption here...'
                }
            },
            {
                'id': 'ig-21',
                'type': 'aiAgent',
                'position': {'x': 450, 'y': 0},
                'data': {
                    'label': 'Instagram Rewrite',
                    'model': 'google/gemini-3.6-flash',
                    'systemPrompt': 'You are an Instagram copywriter. Rewrite the given caption for Instagram: emotional, conversational, 150-220 words, strong hook first line, story-driven body, uplifting CTA at the end, 8-10 hashtags. Output ONLY the rewritten caption.',
                    'user_prompt_template': '{{input}}',
                    'output': None
                }
            },
            {
                'id': 'x-21',
                'type': 'aiAgent',
                'position': {'x': 450, 'y': 220},
                'data': {
                    'label': 'X (Twitter) Rewrite',
                    'model': 'google/gemini-3.6-flash',
                    'systemPrompt': 'You are an X/Twitter copywriter. Rewrite the given caption as a compelling tweet thread (3-5 tweets). Each tweet max 240 characters, numbered 1/, 2/, etc. Make it punchy, direct, and shareable. End with a CTA tweet. Output ONLY the thread.',
                    'user_prompt_template': '{{input}}',
                    'output': None
                }
            },
            {
                'id': 'linkedin-21',
                'type': 'aiAgent',
                'position': {'x': 450, 'y': 480},
                'data': {
                    'label': 'LinkedIn Rewrite',
                    'model': 'google/gemini-3.6-flash',
                    'systemPrompt': 'You are a LinkedIn content writer. Rewrite the given caption for LinkedIn: professional but personal tone, structured with line breaks, start with a bold insight or question, expand with the story (3-4 paragraphs), close with a reflection or question to drive comments. Include 3-5 hashtags. Output ONLY the post.',
                    'user_prompt_template': '{{input}}',
                    'output': None
                }
            },
            {
                'id': 'tiktok-21',
                'type': 'aiAgent',
                'position': {'x': 450, 'y': 700},
                'data': {
                    'label': 'TikTok Rewrite',
                    'model': 'google/gemini-3.6-flash',
                    'systemPrompt': 'You are a TikTok content creator. Rewrite the given caption as a TikTok video hook + caption. Start with a scroll-stopping first line (max 10 words), then a 2-3 sentence caption body for the video description, then 5 trending hashtags. Output ONLY the hook and caption.',
                    'user_prompt_template': '{{input}}',
                    'output': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-caption-ig-21',
                'source': 'caption-21',
                'target': 'ig-21',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-caption-x-21',
                'source': 'caption-21',
                'target': 'x-21',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-caption-linkedin-21',
                'source': 'caption-21',
                'target': 'linkedin-21',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-caption-tiktok-21',
                'source': 'caption-21',
                'target': 'tiktok-21',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 22. Voiceover-ready TikTok Script + 9:16 Visual
    {
        'name': 'TikTok Script + Voiceover + 9:16 Visual',
        'description': 'Enter a topic and get a TikTok-ready voiceover script, an audio file, and a matching vertical keyframe.',
        'category': 'social-media',
        'nodes': [
            {
                'id': 'topic-22',
                'type': 'textInput',
                'position': {'x': 50, 'y': 300},
                'data': {
                    'label': 'TikTok Topic',
                    'text': '3 morning habits that doubled my productivity',
                    'placeholder': 'Enter your TikTok topic or hook...'
                }
            },
            {
                'id': 'script-22',
                'type': 'aiAgent',
                'position': {'x': 400, 'y': 300},
                'data': {
                    'label': 'TikTok Script',
                    'model': 'google/gemini-3.6-flash',
                    'systemPrompt': 'You are a TikTok scriptwriter. Write a 45-60 second voiceover script for the given topic. Structure: Hook (5-7 words, first 3 seconds), 3 points with brief explanations, punchy CTA at the end. Total ~90-120 words. Conversational, energetic tone. Output ONLY the voiceover script text, no stage directions or labels.',
                    'user_prompt_template': '{{input}}',
                    'output': None
                }
            },
            {
                'id': 'voiceover-22',
                'type': 'ttsNode',
                'position': {'x': 750, 'y': 150},
                'data': {
                    'label': 'Voiceover Audio',
                    'model': 'openai/gpt-4o-mini-tts-2025-12-15',
                    'voice': 'nova',
                    'speed': 1.1,
                    'text': '',
                    'audioDataUri': None
                }
            },
            {
                'id': 'keyframe-22',
                'type': 'imageGen',
                'position': {'x': 750, 'y': 450},
                'data': {
                    'label': 'Vertical Keyframe (9:16)',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': 'Vertical 9:16 mobile-first TikTok keyframe image. Bright, modern lifestyle aesthetic with bold visual impact. Clean composition with negative space at top and bottom for text overlay. Vibrant but not gaudy colors. High contrast, scroll-stopping thumbnail quality.',
                    'negativePrompt': 'horizontal, landscape, text overlay, watermark, dark, blurry, low quality',
                    'generatedImage': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-topic-script-22',
                'source': 'topic-22',
                'target': 'script-22',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-script-tts-22',
                'source': 'script-22',
                'target': 'voiceover-22',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-script-image-22',
                'source': 'script-22',
                'target': 'keyframe-22',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 23. A/B Caption Test (2 variants, same image)
    {
        'name': 'A/B Caption Test (2 Variants)',
        'description': 'Upload one product image and generate two distinct caption variants optimized for A/B testing engagement.',
        'category': 'social-media',
        'nodes': [
            {
                'id': 'upload-23',
                'type': 'imageUpload',
                'position': {'x': 50, 'y': 200},
                'data': {
                    'label': 'Upload Product Image',
                    'imageUrl': None
                }
            },
            {
                'id': 'variant-a-23',
                'type': 'aiAgent',
                'position': {'x': 400, 'y': 50},
                'data': {
                    'label': 'Variant A — Emotional',
                    'model': 'google/gemini-3.6-flash',
                    'systemPrompt': 'You are an Instagram copywriter testing caption variant A. Write an emotionally-driven caption for the product in the image. Lead with a relatable feeling or story, connect it to the product benefit, end with a soft CTA. Tone: warm, personal, authentic. Include 6-8 hashtags. Output ONLY the caption.',
                    'user_prompt_template': 'Write an emotional variant A caption for this product image.',
                    'output': None
                }
            },
            {
                'id': 'variant-b-23',
                'type': 'aiAgent',
                'position': {'x': 400, 'y': 350},
                'data': {
                    'label': 'Variant B — Direct/Benefit',
                    'model': 'google/gemini-3.6-flash',
                    'systemPrompt': 'You are an Instagram copywriter testing caption variant B. Write a direct, benefit-focused caption for the product in the image. Lead with the key benefit or result, list 2-3 features as short punchy lines, end with a clear action-oriented CTA. Tone: confident, clear, slightly bold. Include 6-8 hashtags. Output ONLY the caption.',
                    'user_prompt_template': 'Write a direct benefit-focused variant B caption for this product image.',
                    'output': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-upload-a-23',
                'source': 'upload-23',
                'target': 'variant-a-23',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-upload-b-23',
                'source': 'upload-23',
                'target': 'variant-b-23',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            }
        ]
    },

    # 15. 30-Second Product Ad
    {
        'name': '30-Second Product Ad',
        'description': 'Generate a complete 30-second product ad: brief -> script -> hero image -> voiceover + video clip with native audio. Uses Veo 3.1 for video and GPT-4o mini TTS for voiceover.',
        'nodes': [
            {
                'id': 'brief-15',
                'type': 'textInput',
                'position': {'x': 50, 'y': 300},
                'data': {
                    'label': 'Product Brief',
                    'text': 'Sparkling water brand Zest launching a new mango-chili flavor. Target audience: Gen Z. Tone: bold, playful, energetic.',
                    'placeholder': 'Describe your product, target audience, and tone...'
                }
            },
            {
                'id': 'scriptwriter-15',
                'type': 'aiAgent',
                'position': {'x': 400, 'y': 300},
                'data': {
                    'label': 'Scriptwriter',
                    'model': 'google/gemini-2.5-flash-lite',
                    'systemPrompt': 'You are an ad copywriter. Given the product brief, write a ~60-word 30-second voiceover script. Output ONLY the voiceover text - no scene directions, no labels, no markdown.',
                    'user_prompt_template': '{{input}}',
                    'output': None
                }
            },
            {
                'id': 'visual-prompt-15',
                'type': 'aiAgent',
                'position': {'x': 750, 'y': 150},
                'data': {
                    'label': 'Visual Prompt',
                    'model': 'google/gemini-2.5-flash-lite',
                    'systemPrompt': 'You are an art director. Given the ad voiceover text below, write ONE detailed visual prompt for a single hero-shot image that captures the essence of the ad. Keep it under 40 words. Describe composition, lighting, mood, colors. Output ONLY the visual prompt, no preamble.',
                    'user_prompt_template': '{{input}}',
                    'output': None
                }
            },
            {
                'id': 'voiceover-15',
                'type': 'ttsNode',
                'position': {'x': 750, 'y': 500},
                'data': {
                    'label': 'Voiceover',
                    'model': 'openai/gpt-4o-mini-tts-2025-12-15',
                    'voice': 'alloy',
                    'speed': 1.0,
                    'text': '',
                    'audioDataUri': None
                }
            },
            {
                'id': 'keyframe-15',
                'type': 'imageGen',
                'position': {'x': 1100, 'y': 150},
                'data': {
                    'label': 'Keyframe',
                    'model': 'google/gemini-2.5-flash-image',
                    'prompt': '',
                    'negativePrompt': 'blurry, low quality, text, watermark',
                    'generatedImage': None
                }
            },
            {
                'id': 'ad-clip-15',
                'type': 'videoGenNode',
                'position': {'x': 1450, 'y': 300},
                'data': {
                    'label': 'Ad Clip',
                    'model': 'google/veo-3.1',
                    'prompt': '',
                    'duration': 8,
                    'resolution': '1080p',
                    'aspect_ratio': '16:9',
                    'generate_audio': True,
                    'videoUrl': None
                }
            }
        ],
        'edges': [
            {
                'id': 'e-brief-script-15',
                'source': 'brief-15',
                'target': 'scriptwriter-15',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-script-visual-15',
                'source': 'scriptwriter-15',
                'target': 'visual-prompt-15',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-script-tts-15',
                'source': 'scriptwriter-15',
                'target': 'voiceover-15',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-visual-image-15',
                'source': 'visual-prompt-15',
                'target': 'keyframe-15',
                'sourceHandle': 'output',
                'targetHandle': 'input-0'
            },
            {
                'id': 'e-image-video-15',
                'source': 'keyframe-15',
                'target': 'ad-clip-15',
                'sourceHandle': 'output',
                'targetHandle': 'frame_image'
            },
            {
                'id': 'e-visual-video-15',
                'source': 'visual-prompt-15',
                'target': 'ad-clip-15',
                'sourceHandle': 'output',
                'targetHandle': 'prompt_text'
            }
        ]
    }
]


# =============================================================================
# DATABASE FUNCTIONS (SQLAlchemy / Postgres — Phase 6)
# =============================================================================

_HARDCODED_IMAGE_MODELS = {
    'google/gemini-2.5-flash-image',
    'google/gemini-3.1-flash-image',
    'google/gemini-3-pro-image-preview',
    'openai/gpt-5-image-mini',
    'openai/gpt-5-image',
    'openai/gpt-5.4-image-2',
}

# Cheapest image-output model — the live registry lookup that previously
# resolved this dynamically lived against a Mongo collection that's being
# ripped out. Phase 6 keeps the hardcoded fallback only; restore the registry
# query once the OpenRouter catalog moves to Postgres.
_DEFAULT_IMAGE_MODEL = 'google/gemini-2.5-flash-image'


def _apply_default_model_to_template(template: dict, default_model: str) -> dict:
    """Return a copy of the template with all hardcoded image model IDs replaced."""
    t = copy.deepcopy(template)
    for node in t.get('nodes', []):
        if node.get('type') == 'imageGen':
            current = (node.get('data') or {}).get('model')
            if current in _HARDCODED_IMAGE_MODELS:
                node['data']['model'] = default_model
    return t


def seed_workflows(clear=True):
    """Seed 23 workflow templates (15 general + 8 social-media) via ORM."""
    from sqlalchemy import delete as sa_delete
    from app.extensions import db
    from app.models.workflow import Workflow

    print("\n=== Seeding Workflow Templates ===")

    if clear:
        result = db.session.execute(
            sa_delete(Workflow).where(Workflow.is_template.is_(True))
        )
        db.session.commit()
        print(f"Cleared {result.rowcount or 0} existing workflow templates")

    default_model = _DEFAULT_IMAGE_MODEL
    print(f"  [info] Using image model fallback: {default_model}")

    now = datetime.utcnow()
    rows = []
    for template in WORKFLOW_TEMPLATES:
        t = _apply_default_model_to_template(template, default_model)
        rows.append(Workflow(
            user_id=None,
            name=t['name'],
            description=t['description'],
            nodes=t['nodes'],
            edges=t['edges'],
            is_template=True,
            category=t.get('category'),
            visibility='template',
            created_at=now,
            updated_at=now,
        ))
        cat_label = f" [{t['category']}]" if t.get('category') else ''
        print(f"  + {t['name']}{cat_label}")

    db.session.add_all(rows)
    db.session.commit()

    print(f"\nSeeded {len(rows)} workflow templates")
    return len(rows)


def seed_prompts(clear=True):
    """Seed 32 prompt templates via ORM."""
    from sqlalchemy import delete as sa_delete
    from app.extensions import db
    from app.models.prompt_template import PromptTemplate

    print("\n=== Seeding Prompt Templates ===")

    if clear:
        result = db.session.execute(sa_delete(PromptTemplate))
        db.session.commit()
        print(f"Cleared {result.rowcount or 0} existing prompt templates")

    rows = []
    for t in PROMPT_TEMPLATES:
        rows.append(PromptTemplate(
            title=t['name'],
            category=t['category'],
            body=t['template_text'],
            variables=t.get('variables') or [],
            usage_count=0,
            is_seed=True,
        ))
    db.session.add_all(rows)
    db.session.commit()

    # Print summary by category
    categories = {}
    for template in PROMPT_TEMPLATES:
        cat = template['category']
        categories[cat] = categories.get(cat, 0) + 1

    print(f"\nSeeded {len(rows)} prompt templates:")
    for cat, num in sorted(categories.items()):
        print(f"  - {cat}: {num}")

    return len(rows)


def main():
    parser = argparse.ArgumentParser(
        description='Seed database with workflow and prompt templates',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/seed.py                 # Seed all templates
  python scripts/seed.py --workflows     # Only workflow templates (23)
  python scripts/seed.py --prompts       # Only prompt templates (32)
  python scripts/seed.py --no-clear      # Add without clearing existing
        """
    )
    parser.add_argument(
        '--workflows',
        action='store_true',
        help='Seed workflow templates only (23 templates: 15 general + 8 social-media)'
    )
    parser.add_argument(
        '--prompts',
        action='store_true',
        help='Seed prompt templates only (32 templates)'
    )
    parser.add_argument(
        '--no-clear',
        action='store_true',
        help="Don't clear existing data before seeding"
    )
    args = parser.parse_args()

    from app import create_app
    app = create_app()
    with app.app_context():
        try:
            clear = not args.no_clear

            # If no specific flag, seed everything
            seed_all = not args.workflows and not args.prompts

            total = 0
            if args.workflows or seed_all:
                total += seed_workflows(clear)
            if args.prompts or seed_all:
                total += seed_prompts(clear)

            print(f"\n{'='*40}")
            print(f"Successfully seeded {total} total templates!")
            print(f"{'='*40}")

        except Exception as e:
            print(f"\nError: {e}")
            sys.exit(1)


if __name__ == '__main__':
    main()
