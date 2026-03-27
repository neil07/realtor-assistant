#!/usr/bin/env python3
"""
Reel Agent — Async Dispatcher

Executes video generation jobs in the background using asyncio.
Wraps all blocking I/O (Claude API, IMA Studio, ffmpeg) in asyncio.to_thread
so the FastAPI event loop stays responsive.

Parallel execution:
  - Step 2: plan_scenes ‖ generate_script   (both only need analysis)
  - Step 4: render_ai_video ‖ generate_voice (both only need prompts+script)

Concurrency limit: Semaphore(3) — max 3 simultaneous jobs.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator.job_manager import JobManager
    from orchestrator.progress_notifier import ProgressNotifier

# Add scripts dir so we can import capability modules
SCRIPTS_DIR = Path(__file__).parent.parent / "skills" / "listing-video" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

# Quality gate: auto-retry once if overall_score < this threshold
AUTO_RETRY_THRESHOLD = 5

# Max words per scene narration (~15 words ≈ 4s at 3.75 wps)
# Prevents a single scene from dominating the total video duration
MAX_WORDS_PER_SCENE = 15


class QualityGateError(Exception):
    """Raised when a critical quality gate fails — aborts pipeline immediately."""
    pass


def _check_quality_gate(
    gate_name: str,
    checks: list[tuple[bool, str, str]],
    logger,
) -> list[dict]:
    """Run quality gate checks after a pipeline step.

    Args:
        gate_name: e.g. "after_step1_analyze"
        checks: List of (condition_is_bad, message, level).
                level is "critical" or "warning".
        logger: JobLogger instance for recording warnings.

    Returns:
        List of triggered issues: [{"level": str, "message": str}]

    Raises:
        QualityGateError: if any critical check triggers.
    """
    issues = []
    for condition, message, level in checks:
        if condition:
            issues.append({"level": level, "gate": gate_name, "message": message})

    # Log all issues
    warnings = [i for i in issues if i["level"] == "warning"]
    criticals = [i for i in issues if i["level"] == "critical"]

    if warnings:
        logger.log_step_end(f"gate_{gate_name}", {
            "status": "warning",
            "issues": [w["message"] for w in warnings],
        })

    if criticals:
        messages = [c["message"] for c in criticals]
        logger.log_step_end(f"gate_{gate_name}", {
            "status": "critical",
            "issues": messages,
        })
        raise QualityGateError(
            f"Quality gate [{gate_name}] failed: {'; '.join(messages)}"
        )

    return issues


def _persist_artifact(output_dir: str, name: str, data) -> None:
    """Write a pipeline intermediate artifact to the output directory as JSON."""
    import json as _json
    path = os.path.join(output_dir, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent=2)


class Dispatcher:
    """
    Manages the async job queue and executes pipelines.

    Usage:
        dispatcher = Dispatcher(job_manager, notifier)
        await dispatcher.submit(job_id)   # non-blocking, returns immediately
    """

    def __init__(
        self,
        job_manager: "JobManager",
        notifier: "ProgressNotifier",
        max_concurrent: int = 3,
    ):
        self.job_mgr = job_manager
        self.notifier = notifier
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running: dict[str, asyncio.Task] = {}

    async def submit(self, job_id: str) -> None:
        """Non-blocking: fire off a background task for this job."""
        if job_id in self._running:
            return  # already running
        task = asyncio.create_task(
            self._guarded_run(job_id), name=f"job-{job_id}"
        )
        self._running[job_id] = task
        task.add_done_callback(lambda _: self._running.pop(job_id, None))

    async def cancel(self, job_id: str) -> None:
        """Cancel a running job."""
        task = self._running.get(job_id)
        if task and not task.done():
            task.cancel()
        await self.job_mgr.mark_cancelled(job_id)

    async def running_count(self) -> int:
        return len(self._running)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _guarded_run(self, job_id: str) -> None:
        """Acquire semaphore slot then run the pipeline."""
        async with self._semaphore:
            await self._execute_pipeline(job_id)

    async def _execute_pipeline(self, job_id: str) -> None:
        """
        Full pipeline execution for one job.
        On any exception → mark FAILED and notify.
        """
        job = await self.job_mgr.get_job(job_id)
        if not job:
            return

        params = json.loads(job["params"])

        try:
            await self._run_steps(job_id, job, params)
        except asyncio.CancelledError:
            await self.job_mgr.mark_cancelled(job_id)
        except QualityGateError as exc:
            # Critical quality gate — mark failed with clear reason, no retry
            await self.job_mgr.mark_failed(job_id, str(exc), retry_count=0)
            await self.notifier.notify_failed(job_id, str(exc), job)
        except Exception as exc:
            retry_count = (job.get("retry_count") or 0) + 1
            await self.job_mgr.mark_failed(job_id, str(exc), retry_count)
            await self.notifier.notify_failed(job_id, str(exc), job)

    async def _run_steps(self, job_id: str, job: dict, params: dict) -> None:
        """Actual pipeline steps with parallel execution at Steps 2 and 4."""
        import analyze_photos
        import assemble_final
        import generate_script
        import generate_voice
        import plan_scenes
        import profile_manager
        import render_ai_video
        import review_video as reviewer
        import write_video_prompts
        from job_logger import JobLogger

        output_dir = job["output_dir"]
        photo_dir = job["photo_dir"]
        os.makedirs(output_dir, exist_ok=True)

        logger = JobLogger(job_dir=output_dir, job_id=job_id)

        # ── Revision: determine re-run start point ────────────────────
        revision_context = None
        parent_outputs: dict = {}
        re_run_from = "ANALYZING"  # default: full run

        if job.get("revision_context"):
            revision_context = (
                json.loads(job["revision_context"])
                if isinstance(job["revision_context"], str)
                else job["revision_context"]
            )
            re_run_from = revision_context.get("re_run_from", "ANALYZING")

        # Load parent job outputs to avoid re-running unchanged steps
        if job.get("parent_job_id"):
            parent_job = await self.job_mgr.get_job(job["parent_job_id"])
            if parent_job:
                for step in ("analysis", "scenes", "script", "prompts", "clips", "narrations"):
                    val = await self.job_mgr.load_step_output(job["parent_job_id"], step)
                    if val is not None:
                        parent_outputs[step] = val

        # ── Load profile ──────────────────────────────────────────────
        voice_id = None
        if job["agent_phone"]:
            profile = await asyncio.to_thread(
                profile_manager.get_profile, job["agent_phone"]
            )
            if profile:
                params.setdefault("style", profile.get("preferences", {}).get("style", "professional"))
                params.setdefault("music", profile.get("preferences", {}).get("music", "modern"))
                params.setdefault("agent_name", profile.get("name", ""))
                voice_id = profile.get("voice_clone_id")

                # 2.0: inject preference context so models know learned patterns
                pref_context = profile_manager.get_preference_context(job["agent_phone"])
                if pref_context:
                    params.setdefault("preference_context", pref_context)

        # ── Step 0: Collect photo paths ───────────────────────────────
        photo_paths = sorted(
            str(p) for p in Path(photo_dir).iterdir()
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        )
        if not photo_paths:
            raise ValueError("No photos found in directory")

        # ── Step 1: Analyze photos ────────────────────────────────────
        # Skip if revision starts at SCRIPTING or PRODUCING (reuse parent's analysis)
        if re_run_from == "ANALYZING" or "analysis" not in parent_outputs:
            await self.notifier.notify_progress(
                job_id, "analyzing",
                f"Got {len(photo_paths)} photos, analyzing...", job
            )
            await self.job_mgr.update_status(job_id, "ANALYZING", "analyze_photos")
            logger.log_step_start("analyze_photos", {"count": len(photo_paths)})

            analysis = await asyncio.to_thread(analyze_photos.run, photo_paths)
            sorted_photos = analyze_photos.sort_photos(analysis)

            await self.job_mgr.save_step_output(job_id, "analysis", analysis)
            _persist_artifact(output_dir, "analysis", analysis)
            logger.log_step_end("analyze_photos", {"rooms": len(sorted_photos)})

            # Gate: after Step 1
            photos_data = analysis.get("photos", [])
            worthy_count = sum(1 for p in photos_data if p.get("ai_video_worthy"))
            avg_quality = (
                sum(p.get("quality_score", 0) for p in photos_data) / len(photos_data)
                if photos_data else 0
            )
            _check_quality_gate("after_analyze", [
                (worthy_count == 0,
                 f"No photos suitable for AI video (0/{len(photos_data)} marked ai_video_worthy)",
                 "critical"),
                (avg_quality < 3 and len(photos_data) > 0,
                 f"Average photo quality very low ({avg_quality:.1f}/10)",
                 "warning"),
            ], logger)
        else:
            analysis = parent_outputs["analysis"]
            sorted_photos = analyze_photos.sort_photos(analysis)
            await self.job_mgr.save_step_output(job_id, "analysis", analysis)
            _persist_artifact(output_dir, "analysis", analysis)
            logger.log_step_start("analyze_photos", {"reused_from_parent": True})
            logger.log_step_end("analyze_photos", {"skipped": True})

        # ── Step 2: plan_scenes ‖ generate_script (parallel) ─────────
        # Skip if revision starts at PRODUCING (reuse parent's script + scenes)
        if re_run_from in ("ANALYZING", "SCRIPTING") or "scenes" not in parent_outputs:
            await self.job_mgr.update_status(job_id, "SCRIPTING", "plan_and_script")
            logger.log_step_start("scripting", {"parallel": True})

            property_info = (
                f"Address: {params.get('address', '[TBD]')}\n"
                f"Price: {params.get('price', '[TBD]')}\n"
                f"Agent: {params.get('agent_name', '')}"
            )

            scenes, script = await asyncio.gather(
                asyncio.to_thread(
                    plan_scenes.run,
                    photo_dir=photo_dir,
                    property_info=property_info,
                    language=params.get("language", "en"),
                ),
                asyncio.to_thread(
                    generate_script.run,
                    photo_analysis=analysis,
                    address=params.get("address", "[TBD]"),
                    price=params.get("price", "[TBD]"),
                    agent_name=params.get("agent_name", ""),
                    agent_phone=job["agent_phone"],
                ),
            )

            # Overlay the high-quality voiceover script onto scene narrations.
            # video_planner generates structural scene order; generate_script
            # produces the polished hook/walkthrough/closer. We keep the scene
            # structure from the planner but replace its generic narrations with
            # the quality-controlled script segments.
            scenes = _distribute_script_to_scenes(scenes, script)

            await self.job_mgr.save_step_output(job_id, "scenes", scenes)
            await self.job_mgr.save_step_output(job_id, "script", script)
            _persist_artifact(output_dir, "scenes", scenes)
            _persist_artifact(output_dir, "script", script)
            logger.log_step_end("scripting", {
                "scene_count": len(scenes),
                "word_count": script.get("word_count", 0),
            })

            await self.notifier.notify_progress(
                job_id, "scripting",
                f"Script ready ({script.get('word_count', 0)} words), generating video...",
                job,
            )

            # Gate: after Step 2
            word_count = script.get("word_count", 0)
            empty_narrations = sum(
                1 for s in scenes if not (s.get("text_narration") or "").strip()
            )
            _check_quality_gate("after_script", [
                (len(scenes) > len(photo_paths),
                 f"More scenes ({len(scenes)}) than photos ({len(photo_paths)}) — may reuse photos",
                 "warning"),
                (word_count < 20,
                 f"Script too short ({word_count} words) — video will feel empty",
                 "warning"),
                (word_count > 200,
                 f"Script too long ({word_count} words) — will exceed target duration",
                 "warning"),
                (empty_narrations > 0,
                 f"{empty_narrations}/{len(scenes)} scenes have no narration text",
                 "warning"),
            ], logger)
        else:
            scenes = parent_outputs["scenes"]
            script = parent_outputs["script"]
            await self.job_mgr.save_step_output(job_id, "scenes", scenes)
            await self.job_mgr.save_step_output(job_id, "script", script)
            _persist_artifact(output_dir, "scenes", scenes)
            _persist_artifact(output_dir, "script", script)
            logger.log_step_start("scripting", {"reused_from_parent": True})
            logger.log_step_end("scripting", {"skipped": True})

        # ── Step 3: Video prompts (batch, with internal concurrency) ──
        # Skip if revision starts at PRODUCING (reuse parent's prompts)
        if re_run_from in ("ANALYZING", "SCRIPTING") or "prompts" not in parent_outputs:
            await self.job_mgr.update_status(job_id, "PROMPTING", "write_prompts")
            logger.log_step_start("write_prompts", {"scene_count": len(scenes)})

            prompts = await asyncio.to_thread(
                write_video_prompts.run_batch, scenes, photo_dir
            )

            prompt_map = {p["sequence"]: p["motion_prompt"] for p in prompts}
            for scene in scenes:
                scene["motion_prompt"] = prompt_map.get(scene["sequence"], "")

            await self.job_mgr.save_step_output(job_id, "prompts", prompts)
            # Re-save scenes so motion_prompts survive restarts
            await self.job_mgr.save_step_output(job_id, "scenes", scenes)
            _persist_artifact(output_dir, "prompts", prompts)
            _persist_artifact(output_dir, "scenes", scenes)
            logger.log_step_end("write_prompts", {"count": len(prompts)})

            # Gate: after Step 3
            motion_prompts = [p.get("motion_prompt", "") for p in prompts]
            empty_prompts = sum(1 for mp in motion_prompts if not mp.strip())
            unique_prompts = len(set(mp.strip() for mp in motion_prompts if mp.strip()))
            _check_quality_gate("after_prompts", [
                (empty_prompts > 0,
                 f"{empty_prompts}/{len(prompts)} scenes have empty motion prompts",
                 "warning"),
                (unique_prompts == 1 and len(prompts) > 1,
                 "All motion prompts are identical — every scene will look the same",
                 "warning"),
            ], logger)
        else:
            prompts = parent_outputs["prompts"]
            prompt_map = {p["sequence"]: p["motion_prompt"] for p in prompts}
            for scene in scenes:
                scene["motion_prompt"] = prompt_map.get(scene["sequence"], "")
            await self.job_mgr.save_step_output(job_id, "prompts", prompts)
            _persist_artifact(output_dir, "prompts", prompts)

        # ── Step 4: render_ai_video ‖ generate_voice (parallel) ──────
        await self.job_mgr.update_status(job_id, "PRODUCING", "render_and_voice")
        logger.log_step_start("producing", {"parallel": True, "re_run_from": re_run_from})

        clips_dir = os.path.join(output_dir, "clips")
        voice_dir = os.path.join(output_dir, "voice")
        os.makedirs(clips_dir, exist_ok=True)
        os.makedirs(voice_dir, exist_ok=True)

        clips, narrations = await asyncio.gather(
            asyncio.to_thread(
                render_ai_video.generate_all_clips_v2,
                scene_plan=scenes,
                photo_dir=photo_dir,
                output_dir=clips_dir,
                aspect_ratio=params.get("aspect_ratio", "9:16"),
            ),
            asyncio.to_thread(
                generate_voice.generate_scene_voiceovers,
                scenes=scenes,
                output_dir=voice_dir,
                voice_id=voice_id,
                style=params.get("style", "professional"),
            ),
        )

        await self.job_mgr.save_step_output(job_id, "clips", clips)
        await self.job_mgr.save_step_output(job_id, "narrations", narrations)
        logger.log_step_end("producing", {
            "clips": len(clips),
            "narrations": len(narrations),
        })

        # Gate: after Step 4
        successful_clips = [c for c in clips if c.get("status") == "success"]
        successful_tts = [
            n for n in narrations
            if n.get("status") == "success"
            and n.get("audio_path")
            and os.path.exists(n.get("audio_path", ""))
        ]
        _has_any_music = _find_music(
            Path(__file__).parent.parent / "skills" / "listing-video" / "assets" / "music",
            params.get("music", "modern"),
            params.get("style", "professional"),
        ) is not None

        _check_quality_gate("after_produce", [
            (len(successful_clips) == 0,
             f"All {len(clips)} video clips failed to render — no video possible",
             "critical"),
            (len(successful_tts) == 0 and not _has_any_music,
             f"All {len(narrations)} TTS failed and no BGM available — video will be silent",
             "critical"),
            (len(successful_tts) < len(narrations) / 2 and len(narrations) > 0,
             f"TTS success rate low: {len(successful_tts)}/{len(narrations)}",
             "warning"),
        ], logger)

        # ── Step 5: Assemble ──────────────────────────────────────────
        await self.job_mgr.update_status(job_id, "ASSEMBLING", "assemble")
        logger.log_step_start("assemble")

        music_path = _find_music(
            Path(__file__).parent.parent / "skills" / "listing-video" / "assets" / "music",
            params.get("music", "modern"),
            params.get("style", "professional"),
        )

        result = await asyncio.to_thread(
            assemble_final.full_assembly_v2,
            scene_plan=scenes,
            clips_dir=clips_dir,
            narrations=narrations,
            music_path=str(music_path) if music_path else "",
            output_dir=output_dir,
            listing_id=params.get("address", "listing")[:30].replace(" ", "_"),
            aspect_ratio=params.get("aspect_ratio", "9:16"),
            address=params.get("address"),
            price=params.get("price"),
            agent_name=params.get("agent_name"),
            agent_phone=job.get("agent_phone"),
        )

        video_path = result.get("video_path", "")
        logger.log_step_end("assemble", {
            "video_path": video_path,
            "has_audio": result.get("has_audio"),
            "total_duration": result.get("total_duration"),
            "audio_warning": result.get("audio_warning"),
        })

        # Gate: after Step 5
        _check_quality_gate("after_assemble", [
            (not video_path or not os.path.exists(video_path),
             "Final video file does not exist",
             "critical"),
            (video_path and os.path.exists(video_path)
             and os.path.getsize(video_path) == 0,
             "Final video file is 0 bytes",
             "critical"),
            (not result.get("has_audio", True),
             "Final video has no audio stream",
             "warning"),
        ], logger)

        # ── Step 6: Auto video review + quality gate ──────────────────
        review_result = await _run_review(
            reviewer, result, narrations, scenes, params, output_dir, logger,
            label="v1",
        )

        # ── Step 7: Auto-retry if quality gate fails (max 1 retry) ───
        # Retry conditions: score < threshold OR no audio stream
        # Only retry once; reuse script+prompts, re-run render+TTS+assemble.
        is_retry = params.get("_auto_retry", False)
        needs_retry = (
            not is_retry
            and (
                review_result.get("overall_score", 10) < AUTO_RETRY_THRESHOLD
                or not review_result.get("deliverable", True)
            )
        )

        if needs_retry:
            score_v1 = review_result.get("overall_score", 0)
            logger.log_step_start("auto_retry", {
                "reason": "quality_gate",
                "score_v1": score_v1,
                "threshold": AUTO_RETRY_THRESHOLD,
                "deliverable_v1": review_result.get("deliverable"),
            })
            await self.notifier.notify_progress(
                job_id, "assembling",
                f"Quality check: {score_v1}/10 (below threshold). Re-rendering to improve...",
                job,
            )

            clips_dir_v2 = os.path.join(output_dir, "clips_v2")
            voice_dir_v2 = os.path.join(output_dir, "voice_v2")

            clips_v2, narrations_v2 = await asyncio.gather(
                asyncio.to_thread(
                    render_ai_video.generate_all_clips_v2,
                    scene_plan=scenes,
                    photo_dir=photo_dir,
                    output_dir=clips_dir_v2,
                    aspect_ratio=params.get("aspect_ratio", "9:16"),
                ),
                asyncio.to_thread(
                    generate_voice.generate_scene_voiceovers,
                    scenes=scenes,
                    output_dir=voice_dir_v2,
                    voice_id=voice_id,
                    style=params.get("style", "professional"),
                ),
            )

            result_v2 = await asyncio.to_thread(
                assemble_final.full_assembly_v2,
                scene_plan=scenes,
                clips_dir=clips_dir_v2,
                narrations=narrations_v2,
                music_path=str(music_path) if music_path else "",
                output_dir=output_dir,
                listing_id=(params.get("address", "listing")[:30].replace(" ", "_") + "_v2"),
                aspect_ratio=params.get("aspect_ratio", "9:16"),
                address=params.get("address"),
                price=params.get("price"),
                agent_name=params.get("agent_name"),
                agent_phone=job.get("agent_phone"),
            )

            review_v2 = await _run_review(
                reviewer, result_v2, narrations_v2, scenes, params,
                output_dir, logger, label="v2",
            )

            score_v2 = review_v2.get("overall_score", 0)
            logger.log_step_end("auto_retry", {
                "score_v1": score_v1,
                "score_v2": score_v2,
                "winner": "v2" if score_v2 >= score_v1 else "v1",
            })

            # Pick the better version; v2 wins ties (fresher render)
            if score_v2 >= score_v1:
                video_path = result_v2.get("video_path", video_path)
                result = result_v2
                review_result = review_v2

        # ── Deliver ───────────────────────────────────────────────────
        await self.job_mgr.update_status(
            job_id, "DELIVERED",
            current_step="done",
            video_path=video_path,
            completed_at=time.time(),
        )

        logger.log_job_summary({
            "status": "success",
            "video_path": video_path,
            "scene_count": len(scenes),
            "word_count": script.get("word_count", 0),
            "style": params.get("style"),
            "aspect_ratio": params.get("aspect_ratio"),
            "overall_score": review_result.get("overall_score"),
            "deliverable": review_result.get("deliverable"),
            "audio_warning": result.get("audio_warning"),
            "auto_retried": needs_retry,
        })

        # Update profile stats
        if job["agent_phone"]:
            await asyncio.to_thread(
                profile_manager.increment_video_count, job["agent_phone"]
            )

        await self.notifier.notify_delivered(job_id, {**result, "review": review_result}, job)


def _cap_words(text: str, max_words: int = MAX_WORDS_PER_SCENE) -> str:
    """Trim text to at most max_words words, preserving sentence ending."""
    words = text.split()
    if len(words) <= max_words:
        return text
    trimmed = " ".join(words[:max_words])
    if not trimmed.endswith("."):
        trimmed += "."
    return trimmed


def _distribute_script_to_scenes(scenes: list[dict], script: dict) -> list[dict]:
    """
    Overlay voiceover script segments onto scene narrations.

    Maps hook → scene 1, closer → last scene, walkthrough → middle scenes.
    Each scene narration is capped at MAX_WORDS_PER_SCENE (~4s) to prevent
    one long scene from dominating the total video duration.
    """
    n = len(scenes)
    if n == 0 or not script:
        return scenes

    hook = script.get("hook", "").strip()
    walkthrough = script.get("walkthrough", "").strip()
    closer = script.get("closer", "").strip()

    if n == 1:
        combined = " ".join(filter(None, [hook, walkthrough, closer]))
        scenes[0]["text_narration"] = _cap_words(combined)
        return scenes

    if n == 2:
        scenes[0]["text_narration"] = _cap_words(" ".join(filter(None, [hook, walkthrough])))
        scenes[1]["text_narration"] = _cap_words(closer)
        return scenes

    # First scene: hook (capped)
    scenes[0]["text_narration"] = _cap_words(hook)
    # Last scene: closer (capped)
    scenes[-1]["text_narration"] = _cap_words(closer)
    # Middle scenes: split walkthrough by sentences, distribute evenly
    middle = scenes[1:-1]
    sentences = [s.strip() for s in walkthrough.split(". ") if s.strip()]
    if sentences:
        chunk_size = max(1, len(sentences) // len(middle))
        for i, scene in enumerate(middle):
            start = i * chunk_size
            # Last middle scene takes remaining sentences, but still capped
            end = start + chunk_size if i < len(middle) - 1 else len(sentences)
            chunk = ". ".join(sentences[start:end]).strip()
            if chunk and not chunk.endswith("."):
                chunk += "."
            scene["text_narration"] = _cap_words(chunk)

    return scenes


async def _run_review(
    reviewer,
    assemble_result: dict,
    narrations: list,
    scenes: list,
    params: dict,
    output_dir: str,
    logger,
    label: str = "v1",
) -> dict:
    """
    Run auto video review on an assembled result.

    Returns review_result dict (empty dict on failure — never blocks delivery).
    label: "v1" or "v2" — used to name the output file (auto_review_v1.json).
    """
    video_path = assemble_result.get("video_path", "")
    if not video_path or not os.path.exists(video_path):
        return {}

    review_output_dir = os.path.join(output_dir, f"_review_{label}")
    try:
        review_metadata = {
            "duration": assemble_result.get("total_duration", 0),
            "scene_count": assemble_result.get("scenes", len(scenes)),
            "has_audio": assemble_result.get("has_audio", False),
            "narrations_succeeded": assemble_result.get("narrations_succeeded", 0),
            "narrations": narrations,
            "address": params.get("address", ""),
            "price": params.get("price", ""),
            "agent_name": params.get("agent_name", ""),
            "style": params.get("style", "professional"),
        }
        result = await asyncio.to_thread(
            reviewer.review_video,
            video_path=video_path,
            metadata=review_metadata,
            output_dir=review_output_dir,
        )
        # Copy review JSON to main output dir with label
        import shutil
        src = result.get("review_path", "")
        if src and os.path.exists(src):
            dst = os.path.join(output_dir, f"auto_review_{label}.json")
            shutil.copy2(src, dst)
            result["review_path"] = dst

        logger.log_step_end(f"review_{label}", {
            "overall_score": result.get("overall_score"),
            "deliverable": result.get("deliverable"),
            "top_issues": result.get("top_issues", [])[:2],
        })
        return result
    except Exception as exc:
        logger.log_step_end(f"review_{label}", {"status": "error", "message": str(exc)})
        return {}


def _find_music(music_dir: Path, preference: str, style: str) -> Path | None:
    """Find a music file matching preference, or any music file as fallback."""
    if not music_dir.exists():
        return None
    for ext in ("*.mp3", "*.wav", "*.m4a"):
        for f in music_dir.glob(ext):
            if preference.lower() in f.stem.lower() or style.lower() in f.stem.lower():
                return f
    for ext in ("*.mp3", "*.wav", "*.m4a"):
        files = list(music_dir.glob(ext))
        if files:
            return files[0]
    return None
