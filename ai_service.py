import json
import logging
from typing import Dict, List, Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


# ==============================================
#   Инициализация OpenAI API
# ==============================================

client: Optional[AsyncOpenAI] = None

def init_openai(api_key: str) -> None:
    """
    Инициализирует OpenAI API ключ.
    Вызывается один раз при запуске бота.
    """
    global client
    client = AsyncOpenAI(api_key=api_key)
    logger.info("✅ OpenAI API инициализирован")


# ==============================================
#   Список категорий по умолчанию
# ==============================================

DEFAULT_CATEGORIES = {
    "🛒 Покупки",
    "💡 Идеи",
    "🍳 Рецепты",
    "🎬 Фильмы",
    "📚 Книги",
    "🎵 Музыка",
    "🎯 Прочее",
}


# ==============================================
#   Получение доступных категорий
# ==============================================

async def get_available_categories(user_categories: Optional[List[str]] = None) -> List[str]:
    """
    Объединяет категории по умолчанию с существующими категориями пользователя.
    ИИ будет выбирать из этого списка или создавать новую.
    
    Args:
        user_categories: список уже использованных категорий пользователем (или None)
    
    Returns:
        отсортированный список всех доступных категорий
    """
    all_categories = DEFAULT_CATEGORIES.copy()
    
    if user_categories:
        valid_categories = [cat for cat in user_categories if cat is not None]
        all_categories.update(set(valid_categories))
    
    return sorted(list(all_categories))


# ==============================================
#   Основная функция анализа заметки
# ==============================================

async def analyze_note(
    text: str, 
    user_categories: Optional[List[str]] = None
) -> Dict[str, str]:
    """
    Анализирует заметку через OpenAI API.
    Определяет категорию и генерирует развёрнутое описание.
    
    ВАЖНО: 
    - Сохраняет исходный текст как есть
    - Определяет категорию (может быть существующей или новой)
    - Генерирует описание с контекстом, пояснениями и рекомендациями
    
    Args:
        text: текст заметки от пользователя (может быть с ошибками, в спешке и т.д.)
        user_categories: существующие категории пользователя (для контекста)
    
    Returns:
        dict:
        {
            "category": "🛒 Покупки",  # существующая или новая
            "description": "Молочные продукты и хлеб. Можно приготовить..."
        }
    """
    
    available_categories = await get_available_categories(user_categories)
    categories_str = "\n".join(available_categories)
    
    # ════════════════════════════════════════════════════════════
    # Формируем промпт для OpenAI
    # ════════════════════════════════════════════════════════════
    
    prompt = f"""You are a personal note assistant.

Users write short, messy notes — often with typos, slang, or abbreviations.
Your job is to **understand what they meant**, expand abbreviations, and add a bit of practical context.

═══════════════════════════════════════════════════════════════
🎯 YOUR ROLE:
═══════════════════════════════════════════════════════════════
- Be concise and natural, like a calm personal assistant.
- Use **Russian language** only in responses.
- Write **1–2 short sentences (max ~220 characters)**.
- **Never repeat the user’s text** or say “The user wrote...”.
- **Never give advice or instructions** (“check”, “plan”, “make sure”).
- **Never sound like a teacher or consultant**.
- Focus on **clarity and enrichment**, not on telling the user what to do.

═══════════════════════════════════════════════════════════════
🔤 ABBREVIATIONS AND TERMS:
═══════════════════════════════════════════════════════════════
- Always expand abbreviations, acronyms, brand names, and model names.
- If the note is just an abbreviation or name, explain what it is and what it means.
- Be sure to write the correct names in Russian or transliterated form if common (e.g., ChatGPT, V0.dev, Adobe Firefly, Perplexity, Claude).

Examples:
- "Adobe fairfly" → Adobe Firefly — генератор изображений от Adobe.
- "V0" or "V0 io" → v0.dev — платформа ИИ для генерации кода React+TailwindCSS от Vercel.
- "GPT" → ChatGPT — языковая модель от OpenAI.
- "Claude" → Claude — языковая модель от Anthropic.
- "SaaS" → Software as a Service — модель, при которой софт предоставляется по подписке через интернет.


═══════════════════════════════════════════════════════════════
🗂️ CATEGORIES:
═══════════════════════════════════════════════════════════════
{categories_str}

Rules:
1. If the note clearly fits one of the existing categories, choose it.
2. If it doesn’t fit any, **create a new one** (for example: "🎮 Игры", "🤖 ИИ Инструменты", "📺 Аниме", "✈️ Путешествия", "🧠 Саморазвитие").
3. Never say “create new category” — just create it.
4. Use "🎯 Прочее" only if the category is truly unclear.

═══════════════════════════════════════════════════════════════
🧠 DESCRIPTION LOGIC:
═══════════════════════════════════════════════════════════════
Your description must:
- Clarify what the note means or refers to.
- Add a short, meaningful complement — not advice, not motivation.
- Always expand abbreviations and hidden context.
- Use an appropriate tone based on the note type:
    • 🛒 Покупки — mention related ingredients or a short idea for a dish (e.g. “можно взять сыр и масло, если нужно”).
    • 🍳 Рецепты — short suggestion or variant (“можно заменить сливки на молоко”).
    • 🎬 Фильмы / 📺 Аниме — say what it is and the genre, no plot summary.
    • 📚 Книги — author and topic, no retelling.
    • 🎵 Музыка — artist and style, no biography.
    • 🤖 ИИ Инструменты — explain what the tool does and its purpose.
    • For others — one concise clarification of meaning or context.

═══════════════════════════════════════════════════════════════
📝 USER NOTE:
═══════════════════════════════════════════════════════════════
"{text}"

═══════════════════════════════════════════════════════════════
📦 OUTPUT FORMAT:
═══════════════════════════════════════════════════════════════
Return **only valid JSON**, nothing else:

{{
    "category": "existing or new category with emoji",
    "description": "1–2 short sentences in Russian (≤220 characters). Avoid repetition and advice; focus on clarity and context."
}}"""

    try:
        logger.info(f"🤖 Анализирую заметку: '{text}'")
        
        # ════════════════════════════════════════════════════════════
        # Вызываем OpenAI API (новый синтаксис)
        # ════════════════════════════════════════════════════════════
        
        if client is None:
            raise RuntimeError("OpenAI client не инициализирован. Вызови init_openai() первым.")
        
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a personal AI assistant for analyzing and interpreting short notes.\n"
                        "\n"
                        "Follow these permanent rules:\n"
                        "1. Always respond **in Russian language**.\n"
                        "2. Return **only valid JSON** — no explanations, greetings, or comments.\n"
                        "3. Output structure:\n"
                        "{\n"
                        '  "category": "existing or new category with emoji",\n'
                        '  "description": "1–2 short sentences in Russian (≤220 characters). Avoid repetition and advice; focus on clarity and context."\n'
                        "}\n"
                        "4. Be extremely precise when identifying categories and expanding abbreviations.\n"
                        "5. Never output anything except JSON — not even confirmations or formatting notes."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.2,
            max_tokens=220,
            top_p=0.8
        )
        
        # ════════════════════════════════════════════════════════════
        # Парсим ответ
        # ════════════════════════════════════════════════════════════
        
        response_text = response.choices[0].message.content.strip()
        result = json.loads(response_text)
        
        category = result.get("category", "🎯 Прочее").strip()
        description = result.get("description", "").strip()
        
        logger.info(f"✅ Анализ готов: {category}")
        
        return {
            "category": category,
            "description": description
        }
        
    except json.JSONDecodeError as e:
        logger.error(f"❌ ИИ вернул невалидный JSON: {e}")
        logger.error(f"   Ответ был: {response_text if 'response_text' in locals() else 'N/A'}")
        
        # Fallback: вернём категорию по умолчанию
        return {
            "category": "🎯 Прочее",
            "description": "Ошибка при анализе. Заметка сохранена, но описание не создано."
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка при вызове OpenAI API: {e}", exc_info=True)
        
        # Fallback: если API недоступен
        return {
            "category": "🎯 Прочее",
            "description": f"API недоступен: {str(e)}"
        }


# ==============================================
#   Хелпер для проверки валидности категории
# ==============================================

def is_valid_category(category: str) -> bool:
    """
    Проверяет, что категория имеет правильный формат.
    Формат: "ЭМОДЗИ название" (например "🛒 Покупки")
    
    Args:
        category: строка для проверки
    
    Returns:
        True если категория валидна, False иначе
    """
    # Проверяем, что есть пробел и что часть после пробела не пустая
    if not category or " " not in category:
        return False
    
    parts = category.split(" ", 1)
    emoji_part = parts[0]
    name_part = parts[1] if len(parts) > 1 else ""
    
    # Простая проверка: первый символ не ASCII буква/цифра (вероятно эмодзи)
    # и есть название
    return len(emoji_part) > 0 and len(name_part) > 0


# ==============================================
#   Получение рекомендуемых категорий
# ==============================================

async def get_suggested_categories(text: str) -> List[str]:
    """
    Быстро предлагает несколько подходящих категорий на основе текста.
    Может использоваться для UI подсказок (но не для сохранения).
    
    Args:
        text: текст заметки
    
    Returns:
        список из 2-3 предложенных категорий
    """
    # Простая эвристика для быстрого определения
    text_lower = text.lower()
    
    suggestions = []
    
    if any(word in text_lower for word in ["купи", "куп", "магаз", "продукт", "хлеб", "молок", "молоко"]):
        suggestions.append("🛒 Покупки")
    
    if any(word in text_lower for word in ["идея", "думаю", "может", "хочу", "создать", "написать"]):
        suggestions.append("💡 Идеи")
    
    if any(word in text_lower for word in ["рецепт", "готовить", "блюдо", "приготов", "ингредиент"]):
        suggestions.append("🍳 Рецепты")
    
    if any(word in text_lower for word in ["фильм", "кино", "сериал", "посмотр", "видео"]):
        suggestions.append("🎬 Фильмы")
    
    if any(word in text_lower for word in ["книг", "читать", "прочит", "автор", "произведени"]):
        suggestions.append("📚 Книги")
    
    if any(word in text_lower for word in ["музык", "песн", "трек", "артист", "альбом", "композитор"]):
        suggestions.append("🎵 Музыка")
    
    if any(word in text_lower for word in ["аниме", "манга", "серия", "эпизод"]):
        suggestions.append("📺 Аниме")
    
    # Если ничего не подошло или меньше 1 — добавим Прочее
    if not suggestions:
        suggestions.append("🎯 Прочее")
    
    return suggestions[:3]  # Максимум 3 предложения