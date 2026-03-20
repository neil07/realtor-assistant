# Photo Analysis Prompt

You are analyzing real estate listing photos for a marketing video.

For each photo, provide:

```json
{
  "photos": [
    {
      "index": 1,
      "room_type": "exterior|living|kitchen|dining|master_bedroom|bedroom|master_bath|bathroom|backyard|pool|garage|laundry|office|aerial|other",
      "description": "Brief description of what you see",
      "highlights": ["vaulted ceilings", "granite countertops"],
      "style": "modern|traditional|mediterranean|craftsman|farmhouse|contemporary|colonial|mid_century",
      "quality_score": 8,
      "quality_issues": ["slightly dark", "slightly tilted"],
      "ai_video_worthy": true,
      "ai_video_reason": "Pool with water — dynamic motion will look stunning",
      "suggested_motion": "slow_push|pull_back|slide_left|slide_right|crane_down|orbit|zoom_in|static",
      "video_order": 1,
      "duration_suggestion": 3
    }
  ],
  "property_summary": {
    "estimated_style": "Mediterranean",
    "estimated_tier": "mid_range|luxury|starter|investment",
    "bedrooms_detected": 3,
    "bathrooms_detected": 2,
    "key_selling_points": ["heated pool", "renovated kitchen", "mountain views"],
    "missing_shots": ["exterior", "aerial"],
    "overall_quality": "good|excellent|needs_improvement"
  },
  "video_plan": {
    "recommended_duration": 30,
    "ai_clips_count": 3,
    "slideshow_clips_count": 5,
    "recommended_style": "energetic",
    "narrative_arc": "exterior hook → living spaces → kitchen highlight → bedrooms → pool climax → CTA"
  }
}
```

## Rules

1. **Sort by walk-through order**: exterior → entry/foyer → living → kitchen → dining → bedrooms → bathrooms → outdoor/pool → aerial → CTA
2. **AI-worthy criteria**: Water features, exterior shots, views/landscapes, showcase rooms (renovated kitchen, dramatic living room). Small rooms (bathrooms, closets, laundry) are NOT ai-worthy.
3. **Quality scoring** (1-10): Penalize for darkness (-2), blur (-3), tilt (-1), clutter (-1), poor composition (-1).
4. **Be honest about bad photos**: If a photo is unusable, say so. "This bathroom shot is too dark and blurry to use. Got another angle?"
5. **Detect renovations**: New appliances, fresh paint, modern fixtures = recently updated. Mention it.
6. **Count rooms**: Estimate bedrooms and bathrooms from photos to reduce questions.
7. **Duration allocation**: Hero shots (exterior, pool, kitchen) get 3-5s. Standard rooms get 2-3s. Total should fit 15-30s.
