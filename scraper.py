async def rewrite_with_crawl4ai(raw_title, raw_content, default_cat):
    """Crawl4AI LLMExtractionStrategy ద్వారా సొంత తెలుగులో రీరైట్ చేయడం"""
    prompt = build_rewrite_prompt(raw_title, raw_content, default_cat)

    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, LLMConfig
        from crawl4ai.extraction_strategy import LLMExtractionStrategy

        provider = CRAWL4AI_LLM_PROVIDER or (
            "xai/" + GROK_MODEL if XAI_API_KEY else (
                "gemini/" + GEMINI_MODEL if GEMINI_API_KEY else ""
            )
        )
        api_key = CRAWL4AI_LLM_API_KEY or XAI_API_KEY or GEMINI_API_KEY

        if not provider:
            return None

        llm_cfg = LLMConfig(provider=provider, api_token=api_key or None)
        strategy = LLMExtractionStrategy(
            llm_config=llm_cfg,
            instruction=prompt,
            extraction_type="text",
            apply_chunking=False
        )
        run_cfg = CrawlerRunConfig(extraction_strategy=strategy)

        # Crawl4AI కి నేరుగా raw: prefixed HTML ఇవ్వడం
        raw_html_input = f"raw:<html><body><article><p>{html.escape(raw_content[:1800])}</p></article></body></html>"

        async with AsyncWebCrawler() as crawler:
            res = await crawler.arun(url=raw_html_input, config=run_cfg)
            if res and res.success and res.extracted_content:
                parsed = parse_json_loose(res.extracted_content)
                if isinstance(parsed, list) and parsed:
                    parsed = parsed[0]
                if isinstance(parsed, dict) and parsed.get("title") and parsed.get("content"):
                    return parsed
    except Exception as e:
        print(f"Crawl4AI rewrite fallback: {e}")

    # Direct Grok / Gemini API fallback
    if XAI_API_KEY:
        try:
            payload = json.dumps({
                "model": GROK_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a helpful Telugu news editor returning valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.5
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.x.ai/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {XAI_API_KEY}",
                    "User-Agent": "Mozilla/5.0"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                parsed = parse_json_loose(data["choices"][0]["message"]["content"])
                if parsed and parsed.get("title") and parsed.get("content"):
                    return parsed
        except Exception as e:
            print(f"Grok rewrite failed: {e}")

    if GEMINI_API_KEY:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.5, "responseMimeType": "application/json"}
        }).encode("utf-8")
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    parsed = parse_json_loose(data["candidates"][0]["content"]["parts"][0]["text"])
                    if parsed and parsed.get("title") and parsed.get("content"):
                        return parsed
            except Exception as e:
                print(f"Gemini rewrite attempt {attempt + 1} failed: {e}")
                time.sleep(15)

    return None
