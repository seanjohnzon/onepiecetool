"""
AI Chat Service for One Piece TCG card analysis.

Uses Anthropic Claude to provide intelligent analysis of card data,
price trends, flip opportunities, and market insights.
"""

import os
from typing import Optional

from anthropic import Anthropic
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import get_settings


# System prompt that gives Claude context about the database
SYSTEM_PROMPT = """You are an expert One Piece TCG card market analyst and collector advisor. You have access to a comprehensive database of One Piece trading cards with the following data for each card:

- card_name: Character or card name
- card_number: Unique identifier (e.g., OP01-001)
- set_code: Which set the card belongs to (e.g., OP-01, OP-02)
- variant: Card variant type (Base, Alternate Art, Manga, Parallel, Promo, SP, Leader, Championship, etc.)
- price: Current market price in USD
- rarity_score: 1-100 score indicating scarcity (higher = rarer)
- value_score: Calculated value metric
- flip_score: Potential for profitable resale (higher = better flip opportunity)
- trend_score_sma: Simple Moving Average trend (-50 to +50, positive = rising)
- trend_score_ema: Exponential Moving Average trend (-50 to +50, positive = rising)
- sma_30: 30-period Simple Moving Average price
- ema_30: 30-period Exponential Moving Average price

Your role is to:
1. Answer questions about specific cards or characters
2. Identify undervalued cards with flip potential
3. Analyze price trends and predict movements
4. Recommend which cards to buy, hold, or avoid
5. Find "chase cards" - rare variants with high demand
6. Compare cards across different sets
7. Provide market insights and collecting strategies

When analyzing data, consider:
- Cards with high flip_score AND positive trend_score are prime targets
- Manga and Alternate Art variants are typically chase cards
- Championship/Promo cards are limited and often appreciate
- Price vs SMA/EMA can indicate if a card is overbought or oversold

Be concise but insightful. Use specific numbers and card names when possible.
Format prices with $ symbol. Use emojis sparingly for emphasis."""


def get_anthropic_client() -> Optional[Anthropic]:
    """
    Get Anthropic client with API key from environment or config.
    
    Returns:
        Anthropic client or None if no API key available.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY") or get_settings().anthropic_api_key
    if not api_key:
        return None
    return Anthropic(api_key=api_key)


def get_database_summary(db: Session) -> str:
    """
    Generate a summary of the database for Claude's context.
    
    Args:
        db: Database session.
        
    Returns:
        String summary of database statistics.
    """
    # Get basic counts
    total_cards = db.execute(text("SELECT COUNT(*) FROM cards")).scalar()
    
    # Price statistics
    price_stats = db.execute(text("""
        SELECT 
            MIN(price) as min_price,
            MAX(price) as max_price,
            AVG(price) as avg_price,
            COUNT(CASE WHEN price >= 100 THEN 1 END) as cards_100_plus,
            COUNT(CASE WHEN price >= 500 THEN 1 END) as cards_500_plus
        FROM cards WHERE price IS NOT NULL
    """)).fetchone()
    
    # Top characters by card count
    top_chars = db.execute(text("""
        SELECT card_name, COUNT(*) as cnt 
        FROM cards 
        GROUP BY card_name 
        ORDER BY cnt DESC 
        LIMIT 5
    """)).fetchall()
    
    # Set distribution
    sets = db.execute(text("""
        SELECT set_code, COUNT(*) as cnt 
        FROM cards 
        GROUP BY set_code 
        ORDER BY cnt DESC 
        LIMIT 10
    """)).fetchall()
    
    summary = f"""
DATABASE SUMMARY:
- Total cards: {total_cards}
- Price range: ${price_stats[0]:.2f} - ${price_stats[1]:.2f}
- Average price: ${price_stats[2]:.2f}
- Cards $100+: {price_stats[3]}
- Cards $500+: {price_stats[4]}

TOP CHARACTERS: {', '.join([f"{c[0]} ({c[1]})" for c in top_chars])}

SETS: {', '.join([f"{s[0]} ({s[1]})" for s in sets])}
"""
    return summary


def query_relevant_cards(db: Session, user_message: str, limit: int = 20) -> str:
    """
    Query cards relevant to the user's question.
    
    Args:
        db: Database session.
        user_message: User's question to extract context from.
        limit: Maximum cards to return.
        
    Returns:
        Formatted string of relevant card data.
    """
    msg_lower = user_message.lower()
    
    # Build dynamic query based on keywords
    conditions = []
    order_by = "price DESC"
    
    # Check for specific card/character mentions
    if "luffy" in msg_lower:
        conditions.append("LOWER(card_name) LIKE '%luffy%'")
    elif "zoro" in msg_lower:
        conditions.append("LOWER(card_name) LIKE '%zoro%'")
    elif "shanks" in msg_lower:
        conditions.append("LOWER(card_name) LIKE '%shanks%'")
    elif "ace" in msg_lower:
        conditions.append("LOWER(card_name) LIKE '%ace%'")
    elif "nami" in msg_lower:
        conditions.append("LOWER(card_name) LIKE '%nami%'")
    elif "law" in msg_lower or "trafalgar" in msg_lower:
        conditions.append("LOWER(card_name) LIKE '%law%' OR LOWER(card_name) LIKE '%trafalgar%'")
    
    # Check for variant types
    if "manga" in msg_lower:
        conditions.append("LOWER(variant) LIKE '%manga%'")
    elif "alternate art" in msg_lower or "alt art" in msg_lower or " aa " in msg_lower:
        conditions.append("LOWER(variant) LIKE '%alternate%'")
    elif "promo" in msg_lower:
        conditions.append("LOWER(variant) LIKE '%promo%'")
    elif "championship" in msg_lower:
        conditions.append("LOWER(variant) LIKE '%championship%'")
    elif "parallel" in msg_lower or "foil" in msg_lower:
        conditions.append("LOWER(variant) LIKE '%parallel%' OR LOWER(variant) LIKE '%foil%'")
    
    # Check for analysis type
    if "flip" in msg_lower or "undervalued" in msg_lower or "opportunity" in msg_lower:
        conditions.append("flip_score IS NOT NULL AND flip_score > 0")
        order_by = "flip_score DESC"
    elif "trending" in msg_lower or "rising" in msg_lower:
        conditions.append("trend_score_sma > 0")
        order_by = "trend_score_sma DESC"
    elif "falling" in msg_lower or "dropping" in msg_lower:
        conditions.append("trend_score_sma < 0")
        order_by = "trend_score_sma ASC"
    elif "expensive" in msg_lower or "valuable" in msg_lower or "high value" in msg_lower:
        order_by = "price DESC"
    elif "cheap" in msg_lower or "budget" in msg_lower or "affordable" in msg_lower:
        conditions.append("price < 50")
        order_by = "flip_score DESC"
    elif "chase" in msg_lower or "rare" in msg_lower:
        conditions.append("rarity_score >= 40 OR LOWER(variant) LIKE '%manga%' OR LOWER(variant) LIKE '%alternate%'")
        order_by = "rarity_score DESC, price DESC"
    
    # Price range checks
    if "$100" in msg_lower or "100+" in msg_lower:
        conditions.append("price >= 100")
    elif "$500" in msg_lower or "500+" in msg_lower:
        conditions.append("price >= 500")
    elif "$1000" in msg_lower or "1000+" in msg_lower:
        conditions.append("price >= 1000")
    
    # Build WHERE clause
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    query = f"""
        SELECT card_name, card_number, set_code, variant, price,
               rarity_score, flip_score, trend_score_sma, trend_score_ema,
               sma_30, ema_30
        FROM cards
        WHERE {where_clause}
        ORDER BY {order_by}
        LIMIT {limit}
    """
    
    results = db.execute(text(query)).fetchall()
    
    if not results:
        # Fallback to top flip opportunities
        results = db.execute(text("""
            SELECT card_name, card_number, set_code, variant, price,
                   rarity_score, flip_score, trend_score_sma, trend_score_ema,
                   sma_30, ema_30
            FROM cards
            WHERE flip_score IS NOT NULL
            ORDER BY flip_score DESC
            LIMIT 15
        """)).fetchall()
    
    # Format results
    cards_data = []
    for r in results:
        card_info = f"• {r[0]} ({r[1]}) - {r[3] or 'Base'}"
        card_info += f" | ${r[4]:.2f}" if r[4] else ""
        card_info += f" | Flip: {r[6]:.1f}" if r[6] else ""
        card_info += f" | Trend: {r[7]:+.1f}" if r[7] else ""
        cards_data.append(card_info)
    
    return "\n".join(cards_data) if cards_data else "No matching cards found."


def chat_with_claude(
    db: Session,
    user_message: str,
    conversation_history: list[dict] = None
) -> dict:
    """
    Send a message to Claude with card database context.
    
    Args:
        db: Database session.
        user_message: User's question or request.
        conversation_history: Previous messages in the conversation.
        
    Returns:
        dict with 'response' (Claude's reply), 'error' (if any), and 'suggested_cards'.
    """
    client = get_anthropic_client()
    if not client:
        return {
            "response": None,
            "error": "No API key configured. Please set ANTHROPIC_API_KEY environment variable.",
            "suggested_cards": []
        }
    
    # Get database context
    db_summary = get_database_summary(db)
    relevant_cards_text = query_relevant_cards(db, user_message)
    
    # Get actual card objects for suggestions
    suggested_cards = get_suggested_cards(db, user_message)
    
    # Build context message
    context = f"""
{db_summary}

RELEVANT CARDS FOR THIS QUERY:
{relevant_cards_text}
"""
    
    # Build messages array
    messages = []
    
    # Add conversation history if provided
    if conversation_history:
        for msg in conversation_history[-6:]:  # Keep last 6 messages for context
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })
    
    # Add current message with context
    full_message = f"""Based on this database context:
{context}

User question: {user_message}

IMPORTANT: When recommending specific cards, mention them by name and card number (e.g., "Monkey.D.Luffy (OP07-091)") so the user can add them to their lot."""
    
    messages.append({
        "role": "user",
        "content": full_message
    })
    
    try:
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages
        )
        
        return {
            "response": response.content[0].text,
            "error": None,
            "suggested_cards": suggested_cards[:10]  # Limit to 10 suggestions
        }
    except Exception as e:
        # Log the error for debugging
        print(f"AI Chat Error: {e}")
        return {
            "response": f"AI Error: {str(e)}",
            "error": str(e),
            "suggested_cards": []
        }


def get_suggested_cards(db: Session, user_message: str, limit: int = 10) -> list[dict]:
    """
    Get card objects to suggest based on user's query.
    
    Args:
        db: Database session.
        user_message: User's query.
        limit: Max cards to return.
        
    Returns:
        List of card dicts suitable for frontend display.
    """
    msg_lower = user_message.lower()
    
    # Build query conditions
    conditions = []
    order_by = "flip_score DESC"
    
    # Character filters
    if "luffy" in msg_lower:
        conditions.append("LOWER(card_name) LIKE '%luffy%'")
    elif "zoro" in msg_lower:
        conditions.append("LOWER(card_name) LIKE '%zoro%'")
    elif "shanks" in msg_lower:
        conditions.append("LOWER(card_name) LIKE '%shanks%'")
    elif "ace" in msg_lower:
        conditions.append("LOWER(card_name) LIKE '%ace%'")
    elif "nami" in msg_lower:
        conditions.append("LOWER(card_name) LIKE '%nami%'")
    elif "law" in msg_lower or "trafalgar" in msg_lower:
        conditions.append("(LOWER(card_name) LIKE '%law%' OR LOWER(card_name) LIKE '%trafalgar%')")
    
    # Variant filters
    if "manga" in msg_lower:
        conditions.append("LOWER(variant) LIKE '%manga%'")
    elif "alternate art" in msg_lower or "alt art" in msg_lower:
        conditions.append("LOWER(variant) LIKE '%alternate%'")
    elif "promo" in msg_lower:
        conditions.append("LOWER(variant) LIKE '%promo%'")
    
    # Query type
    if "flip" in msg_lower or "undervalued" in msg_lower:
        conditions.append("flip_score > 100")
        order_by = "flip_score DESC"
    elif "trending" in msg_lower or "rising" in msg_lower:
        conditions.append("trend_score_sma > 0")
        order_by = "trend_score_sma DESC"
    elif "expensive" in msg_lower or "valuable" in msg_lower:
        order_by = "price DESC"
    elif "cheap" in msg_lower or "budget" in msg_lower:
        conditions.append("price < 50")
    
    # Price range from message
    if "$400" in msg_lower or "400 dollars" in msg_lower:
        conditions.append("price BETWEEN 10 AND 100")
    elif "$100" in msg_lower:
        conditions.append("price >= 100")
    elif "$500" in msg_lower:
        conditions.append("price >= 500")
    
    # Ensure we have valid cards with prices
    conditions.append("price > 0.5")
    
    where = " AND ".join(conditions) if conditions else "price > 0.5"
    
    query = f"""
        SELECT id, card_name, card_number, variant, price, 
               image_url, image_path, market_url, flip_score, trend_score_sma
        FROM cards
        WHERE {where}
        ORDER BY {order_by}
        LIMIT {limit}
    """
    
    from sqlalchemy import text
    results = db.execute(text(query)).fetchall()
    
    return [
        {
            "id": r[0],
            "card_name": r[1],
            "card_number": r[2],
            "variant": r[3],
            "price": r[4],
            "image_url": r[5] or r[6],
            "market_url": r[7],
            "flip_score": r[8],
            "trend_score_sma": r[9]
        }
        for r in results
    ]


def get_quick_analysis(db: Session, analysis_type: str) -> dict:
    """
    Get pre-built analysis for common queries.
    
    Args:
        db: Database session.
        analysis_type: Type of analysis (top_flips, trending, chase, etc.)
        
    Returns:
        dict with analysis results.
    """
    queries = {
        "top_flips": """
            SELECT card_name, variant, price, flip_score, trend_score_sma
            FROM cards
            WHERE flip_score IS NOT NULL AND price >= 5
            ORDER BY flip_score DESC
            LIMIT 10
        """,
        "trending_up": """
            SELECT card_name, variant, price, trend_score_sma, sma_30
            FROM cards
            WHERE trend_score_sma > 20 AND price >= 10
            ORDER BY trend_score_sma DESC
            LIMIT 10
        """,
        "trending_down": """
            SELECT card_name, variant, price, trend_score_sma, sma_30
            FROM cards
            WHERE trend_score_sma < -20 AND price >= 10
            ORDER BY trend_score_sma ASC
            LIMIT 10
        """,
        "chase_cards": """
            SELECT card_name, variant, price, rarity_score
            FROM cards
            WHERE (LOWER(variant) LIKE '%manga%' OR LOWER(variant) LIKE '%alternate%')
                  AND price >= 50
            ORDER BY price DESC
            LIMIT 10
        """,
        "undervalued": """
            SELECT card_name, variant, price, flip_score, trend_score_sma
            FROM cards
            WHERE flip_score > 150 AND trend_score_sma > 0 AND price < 100
            ORDER BY flip_score DESC
            LIMIT 10
        """
    }
    
    if analysis_type not in queries:
        return {"error": f"Unknown analysis type: {analysis_type}"}
    
    results = db.execute(text(queries[analysis_type])).fetchall()
    
    return {
        "type": analysis_type,
        "cards": [
            {
                "name": r[0],
                "variant": r[1],
                "price": r[2],
                "score": r[3],
                "secondary": r[4] if len(r) > 4 else None
            }
            for r in results
        ]
    }
