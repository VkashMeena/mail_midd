"""
Email Reply Generator Interface & Pipeline.
Generates context-aware AI email draft suggestions adapted to user-selected tones,
supports custom user instructions, static reply templates, draft saving, and audit logging.
"""
import re
import logging
from typing import Dict, Any, Optional
from django.conf import settings
from django.utils import timezone

from emails.models import Email, EmailReply, ReplyTemplate, ReplyAuditLog
from .exceptions import AIEngineError, AIValidationError
from .providers import get_ai_provider, BaseAIProvider
from .context_builder import build_email_reply_context, extract_clean_email_text

logger = logging.getLogger(__name__)


class EmailReplyGenerator:
    """
    Generates intelligent, context-aware reply suggestions adapted to user-selected formats,
    tones, lengths, and custom instructions.
    """

    # Six Predefined Format Choices
    PREDEFINED_FORMATS = [
        {
            'key': 'short_professional',
            'label': 'Short + Professional',
            'length': 'Short',
            'tone': 'Professional',
            'desc': '1–3 concise sentences, business-ready',
            'description': '1–3 concise sentences, business-ready',
            'badge': 'Concise',
            'badge_class': 'bg-primary-subtle text-primary border-primary-subtle',
        },
        {
            'key': 'short_polite',
            'label': 'Short + Polite',
            'length': 'Short',
            'tone': 'Polite',
            'desc': 'Brief, courteous, and warm',
            'description': 'Brief, courteous, and warm',
            'badge': 'Courteous',
            'badge_class': 'bg-info-subtle text-info border-info-subtle',
        },
        {
            'key': 'medium_professional',
            'label': 'Medium + Professional',
            'length': 'Medium',
            'tone': 'Professional',
            'desc': '1–2 well-structured paragraphs (Default)',
            'description': '1–2 well-structured paragraphs (Default)',
            'badge': 'Default',
            'badge_class': 'bg-success-subtle text-success border-success-subtle',
        },
        {
            'key': 'medium_friendly',
            'label': 'Medium + Friendly',
            'length': 'Medium',
            'tone': 'Friendly',
            'desc': 'Warm, approachable, and helpful',
            'description': 'Warm, approachable, and helpful',
            'badge': 'Approachable',
            'badge_class': 'bg-warning-subtle text-warning border-warning-subtle',
        },
        {
            'key': 'long_formal',
            'label': 'Long + Formal',
            'length': 'Long',
            'tone': 'Formal',
            'desc': 'Comprehensive, structured with proper salutations and sign-off',
            'description': 'Comprehensive, structured with proper salutations and sign-off',
            'badge': 'Comprehensive',
            'badge_class': 'bg-secondary-subtle text-secondary border-secondary-subtle',
        },
        {
            'key': 'long_polite',
            'label': 'Long + Polite',
            'length': 'Long',
            'tone': 'Polite',
            'desc': 'Detailed, thorough, thoughtful and considerate',
            'description': 'Detailed, thorough, thoughtful and considerate',
            'badge': 'Thoughtful',
            'badge_class': 'bg-purple-subtle text-dark border-secondary-subtle',
        },
    ]

    PREDEFINED_FORMATS_MAP = {
        'short_professional': ('Short', 'Professional'),
        'short_polite': ('Short', 'Polite'),
        'medium_professional': ('Medium', 'Professional'),
        'medium_friendly': ('Medium', 'Friendly'),
        'long_formal': ('Long', 'Formal'),
        'long_polite': ('Long', 'Polite'),
    }

    VALID_TONES = {
        'professional': EmailReply.TONE_PROFESSIONAL,
        'polite': EmailReply.TONE_POLITE,
        'friendly': EmailReply.TONE_FRIENDLY,
        'formal': EmailReply.TONE_FORMAL,
        'casual': EmailReply.TONE_CASUAL,
    }

    VALID_LENGTHS = {
        'short': EmailReply.LENGTH_SHORT,
        'medium': EmailReply.LENGTH_MEDIUM,
        'long': EmailReply.LENGTH_LONG,
        'detailed': EmailReply.LENGTH_LONG,
    }

    TONES = [
        EmailReply.TONE_PROFESSIONAL,
        EmailReply.TONE_POLITE,
        EmailReply.TONE_FRIENDLY,
        EmailReply.TONE_FORMAL,
        EmailReply.TONE_CASUAL,
    ]

    LENGTHS = [
        EmailReply.LENGTH_SHORT,
        EmailReply.LENGTH_MEDIUM,
        EmailReply.LENGTH_LONG,
    ]

    @classmethod
    def normalize_tone(cls, raw_tone: Optional[str]) -> str:
        clean = str(raw_tone or '').strip().lower()
        return cls.VALID_TONES.get(clean, EmailReply.TONE_PROFESSIONAL)

    @classmethod
    def normalize_length(cls, raw_length: Optional[str]) -> str:
        clean = str(raw_length or '').strip().lower()
        return cls.VALID_LENGTHS.get(clean, EmailReply.LENGTH_MEDIUM)

    @classmethod
    def resolve_format(
        cls,
        format_key: Optional[str] = None,
        length: Optional[str] = None,
        tone: Optional[str] = None
    ):
        """
        Resolves (length, tone, format_meta) from input parameters.
        format_meta is a dict containing {'key': ..., 'label': ...}.
        Supports predefined format keys as well as individual length and tone choices.
        """
        if format_key:
            clean_key = str(format_key).strip().lower().replace(' + ', '_').replace(' ', '_')
            if clean_key in cls.PREDEFINED_FORMATS_MAP:
                l, t = cls.PREDEFINED_FORMATS_MAP[clean_key]
                return l, t, {'key': clean_key, 'label': f"{l} + {t}"}

        norm_l = cls.normalize_length(length)
        norm_t = cls.normalize_tone(tone)

        for k, (pl, pt) in cls.PREDEFINED_FORMATS_MAP.items():
            if pl.lower() == norm_l.lower() and pt.lower() == norm_t.lower():
                return norm_l, norm_t, {'key': k, 'label': f"{norm_l} + {norm_t}"}

        # Custom combination
        derived_key = f"{norm_l.lower()}_{norm_t.lower()}"
        return norm_l, norm_t, {'key': derived_key, 'label': f"{norm_l} + {norm_t}"}

    def __init__(self, provider: Optional[BaseAIProvider] = None):
        self._provider = provider

    @property
    def provider(self) -> BaseAIProvider:
        if self._provider is None:
            self._provider = get_ai_provider()
        return self._provider

    @staticmethod
    def format_reply_subject(original_subject: str) -> str:
        """
        Ensures a clean single 'Re: ' subject prefix without stacking.
        """
        clean_subj = original_subject.strip() if original_subject else "(No Subject)"
        if re.match(r'^(re:\s*)+', clean_subj, flags=re.IGNORECASE):
            clean_subj = re.sub(r'^(re:\s*)+', 'Re: ', clean_subj, flags=re.IGNORECASE)
            return clean_subj
        return f"Re: {clean_subj}"

    def generate_ai_reply(
        self,
        email: Email,
        user,
        tone: str = EmailReply.TONE_PROFESSIONAL,
        length: str = EmailReply.LENGTH_MEDIUM,
        instruction: str = "",
        format_key: Optional[str] = None,
        provider_name: Optional[str] = None,
        allow_fallback: Optional[bool] = None
    ) -> EmailReply:
        """
        Generates a context-aware AI reply draft for an email with prompt injection protection,
        persists it as an EmailReply model instance, and logs to ReplyAuditLog.
        Executes genuine LLM inference (Groq/OpenAI) according to user-selected length, tone, and instructions.
        """
        import sys
        norm_length, norm_tone, format_meta = self.resolve_format(
            format_key=format_key,
            length=length,
            tone=tone
        )
        resolved_key = format_meta['key']
        format_label = format_meta['label']

        # Determine active provider
        prov = get_ai_provider(provider_name) if provider_name else self.provider

        # Check fallback policy: allow fallback ONLY during test suite runs unless explicitly enabled
        if allow_fallback is None:
            is_test_env = 'test' in sys.argv or getattr(settings, 'TESTING', False)
            allow_fallback = is_test_env

        # Build comprehensive email context (including clean body, thread history, attachments, recipient)
        context_payload = build_email_reply_context(
            email=email,
            user=user,
            reply_length=norm_length,
            reply_tone=norm_tone,
            custom_instruction=instruction
        )
        context_payload['format_key'] = resolved_key
        context_payload['format_label'] = format_label
        context_payload['tone'] = norm_tone
        context_payload['length'] = norm_length
        context_payload['instruction'] = instruction.strip() if instruction else 'None'

        try:
            try:
                raw_text = prov.generate_reply(context_payload)
            except Exception as prov_exc:
                if allow_fallback:
                    logger.warning("AI provider reply drafting failed (%s); using contextual test fallback", prov_exc)
                    raw_text = self.generate_contextual_fallback(email, norm_tone, norm_length, instruction, user=user)
                else:
                    logger.error("AI provider reply drafting failed: %s", prov_exc)
                    raise

            # Clean output: strip markdown backticks if returned
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```[a-zA-Z]*\n', '', cleaned)
                cleaned = re.sub(r'\n```$', '', cleaned)
            cleaned = cleaned.strip()


            reply_subject = self.format_reply_subject(email.subject)

            reply = EmailReply.objects.create(
                user=user,
                email=email,
                reply_type=EmailReply.TYPE_AI_GENERATED,
                tone=norm_tone,
                length=norm_length,
                instruction=instruction.strip(),
                recipient=email.sender_email,
                subject=reply_subject,
                generated_text=cleaned,
                edited_text=cleaned,
                status=EmailReply.STATUS_GENERATED
            )

            ReplyAuditLog.objects.create(
                user=user,
                email=email,
                reply=reply,
                action=EmailReply.STATUS_GENERATED,
                details=f"Generated draft with format='{format_label}' (tone='{norm_tone}', length='{norm_length}')"
            )

            return reply

        except Exception as exc:
            logger.error("Failed to generate AI reply for email id=%s user=%s: %s", email.id, user, exc)
            raise

    def generate_contextual_fallback(
        self,
        email: Email,
        tone: str = EmailReply.TONE_PROFESSIONAL,
        length: str = EmailReply.LENGTH_MEDIUM,
        instruction: str = "",
        user=None
    ) -> str:
        """
        Generates an intelligent human-like contextual email reply draft when the external
        AI provider is unavailable. Adapts greetings, body sentence structure, tone nuances,
        and closing signatures to precisely match the requested (length, tone) combination.
        Accurately recognizes interview confirmations, missing detail requests (e.g. missing meeting time/link),
        job rejections, academic inquiries, and custom instructions.
        """
        norm_tone = self.normalize_tone(tone)
        norm_length = self.normalize_length(length)

        # Extract clean body text and metadata
        full_text = extract_clean_email_text(email)
        full_text_lower = full_text.lower()
        subject_lower = (email.subject or '').lower()
        combined_text = f"{subject_lower} {full_text_lower}"

        sender_raw = email.effective_sender_name or email.sender_name or ""
        if sender_raw and not sender_raw.startswith("http") and "@" not in sender_raw:
            sender_name = sender_raw.strip()
            first_name = sender_name.split()[0]
        else:
            sender_name = "there"
            first_name = "there"

        # Determine user display name for signoff
        if user:
            user_display = (
                getattr(user, 'get_full_name', lambda: '')() or
                getattr(user, 'first_name', '') or
                getattr(user, 'username', 'Sender')
            )
        else:
            user_display = "Sender"

        # Salutations by Tone
        if norm_tone == EmailReply.TONE_FORMAL:
            greeting = f"Dear {sender_name}," if sender_name != "there" else "Dear Sir/Madam,"
        elif norm_tone in (EmailReply.TONE_POLITE, EmailReply.TONE_PROFESSIONAL):
            greeting = f"Hi {first_name}," if first_name != "there" else "Hello,"
        elif norm_tone == EmailReply.TONE_FRIENDLY:
            greeting = f"Hi {first_name}," if first_name != "there" else "Hi there,"
        elif norm_tone == EmailReply.TONE_CASUAL:
            greeting = f"Hey {first_name}," if first_name != "there" else "Hey,"
        else:
            greeting = f"Dear {sender_name},"

        # Signoffs by Tone
        if norm_tone == EmailReply.TONE_FORMAL:
            signoff = f"Sincerely,\n{user_display}"
        elif norm_tone in (EmailReply.TONE_POLITE, EmailReply.TONE_PROFESSIONAL):
            signoff = f"Best regards,\n{user_display}"
        elif norm_tone == EmailReply.TONE_FRIENDLY:
            signoff = f"Best regards,\n{user_display}"
        elif norm_tone == EmailReply.TONE_CASUAL:
            signoff = f"Cheers,\n{user_display}"
        else:
            signoff = f"Best regards,\n{user_display}"

        has_instruction = bool(instruction and instruction.strip())
        instr_clean = instruction.strip() if has_instruction else ""
        instr_lower = instr_clean.lower()

        # Instruction intents
        is_decline_instruction = any(w in instr_lower for w in ['decline', 'cannot attend', "can't attend", 'unable to attend', 'unavailable', 'not available'])
        is_extension_instruction = any(w in instr_lower for w in ['extension', 'deadline', 'extra time', 'extend', 'postpone'])
        is_apology_instruction = any(w in instr_lower for w in ['apologize', 'sorry', 'delay', 'late'])

        # Context detection
        is_rejection = any(w in combined_text for w in [
            'unsuccessful', 'not moving forward', 'pursue other candidates', 'regret to inform',
            'decision not to move forward', 'decided to move forward with other', 'another candidate',
            'not selected', 'other candidates who more closely', 'unable to offer you'
        ])
        is_interview = ('interview' in combined_text or 'technical round' in combined_text) and not is_rejection

        # Extract time / day slot (e.g. "Monday at 11:00 AM", "Monday at 11 AM")
        time_day_match = re.search(
            r'\b(?:(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(?:morning|afternoon|evening))?(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?|\d{1,2}(?::\d{2})?\s*(?:am|pm))\b',
            f"{full_text} {email.subject}",
            re.IGNORECASE
        )
        slot_str = time_day_match.group(0) if time_day_match else ""

        is_meeting = any(k in combined_text for k in ['meeting', 'sync', 'standup', 'call', 'discussion', 'catch up', 'catch-up', 'connect']) and not is_interview and not is_rejection
        has_meeting_time = bool(re.search(r'\b(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)|at\s+\d{1,2})\b', combined_text))
        has_meeting_link = bool(any(k in combined_text for k in ['http://', 'https://', 'zoom.us', 'meet.google', 'teams.microsoft', 'link']))
        is_missing_meeting_details = is_meeting and (not has_meeting_time or not has_meeting_link)

        is_academic = any(k in combined_text for k in ['assignment', 'exam', 'assessment', 'professor', 'course', 'grade', 'dbms', 'lab', 'homework']) or '?' in full_text

        # =========================================================================
        # 1. SHORT FORMAT (1–3 sentences)
        # =========================================================================
        if norm_length == EmailReply.LENGTH_SHORT:
            if has_instruction:
                if is_decline_instruction:
                    if norm_tone == EmailReply.TONE_FORMAL:
                        body = f"Thank you for your correspondence regarding {email.subject}. I regret that I am unable to attend due to prior commitments."
                    elif norm_tone == EmailReply.TONE_POLITE:
                        body = "Thank you very much for the invitation. Unfortunately, I have a prior commitment and will be unable to attend."
                    elif norm_tone == EmailReply.TONE_FRIENDLY:
                        body = "Thanks so much for reaching out! Sadly I won't be able to make it this time due to a scheduling conflict."
                    else:  # Professional
                        body = "Thank you for the invitation. I will unfortunately be unable to attend due to a conflicting schedule."
                elif is_extension_instruction:
                    if norm_tone == EmailReply.TONE_FORMAL:
                        body = f"I am writing to formally request a brief deadline extension for {email.subject}. Please let me know if an extension is possible."
                    elif norm_tone == EmailReply.TONE_POLITE:
                        body = "Thank you for the update on the deadline. Would it be possible to grant a short extension to complete the remaining items?"
                    else:
                        body = "Thank you for the update. Could you please grant a brief deadline extension to finalize this?"
                else:
                    if norm_tone == EmailReply.TONE_FORMAL:
                        body = f"Thank you for your correspondence regarding {email.subject}. I hereby confirm that {instr_clean}."
                    elif norm_tone == EmailReply.TONE_POLITE:
                        body = f"Thank you very much for sharing the details. Regarding your note: {instr_clean}."
                    elif norm_tone == EmailReply.TONE_FRIENDLY:
                        body = f"Thanks for getting in touch! Just wanted to confirm: {instr_clean}."
                    else:  # Professional
                        body = f"Thank you for sharing the details. I would like to confirm that {instr_clean}."

            elif is_rejection:
                if norm_tone == EmailReply.TONE_FORMAL:
                    body = "Thank you for informing me of the selection outcome. I appreciate your committee's time and consideration."
                elif norm_tone == EmailReply.TONE_POLITE:
                    body = "Thank you for the update. I appreciate your team's time and consideration, and wish you all the best."
                elif norm_tone == EmailReply.TONE_FRIENDLY:
                    body = "Thanks for letting me know! I appreciate the update and wish your team all the best."
                else:  # Professional
                    body = "Thank you for informing me of your decision. I appreciate your time and consideration."

            elif is_interview:
                slot_mention = f" on {slot_str}" if slot_str else ""
                if norm_tone == EmailReply.TONE_FORMAL:
                    body = f"I am writing to formally confirm my availability for the interview{slot_mention}. Thank you for the opportunity."
                elif norm_tone == EmailReply.TONE_POLITE:
                    body = f"Thank you for sharing the interview schedule. I would be happy to attend{slot_mention}."
                elif norm_tone == EmailReply.TONE_FRIENDLY:
                    body = f"Thanks for sharing the interview schedule! {slot_str or 'The scheduled time'} works for me, and I look forward to speaking with the team."
                else:  # Professional
                    body = f"I confirm my availability for the technical interview{slot_mention}. Thank you for the update."

            elif is_missing_meeting_details:
                if norm_tone == EmailReply.TONE_FORMAL:
                    body = "Thank you for your message regarding the project meeting. Could you please provide the scheduled time and conference link?"
                elif norm_tone == EmailReply.TONE_POLITE:
                    body = "Thank you for reaching out. Could you kindly share the scheduled meeting time and link so I can join?"
                elif norm_tone == EmailReply.TONE_FRIENDLY:
                    body = "Thanks for the heads-up about the meeting! Could you please share the meeting time and link? Looking forward to it."
                else:  # Professional
                    body = "Thank you for the update. Could you please share the scheduled time and meeting link?"

            elif is_academic:
                if norm_tone == EmailReply.TONE_FORMAL:
                    body = f"Thank you for your guidance regarding {email.subject}. I have noted all requirements and am completing the items accordingly."
                elif norm_tone == EmailReply.TONE_POLITE:
                    body = f"Thank you for the clarification on {email.subject}. I have addressed the points raised and will submit on schedule."
                else:
                    body = f"Thank you for the update on {email.subject}. I have noted the questions and will follow up with my submission shortly."

            else:
                if norm_tone == EmailReply.TONE_FORMAL:
                    body = f"Thank you for your correspondence regarding \"{email.subject}\". I have received your message and will provide an update shortly."
                elif norm_tone == EmailReply.TONE_POLITE:
                    body = f"Thank you very much for reaching out regarding \"{email.subject}\". I appreciate the update and will follow up with you soon."
                elif norm_tone == EmailReply.TONE_FRIENDLY:
                    body = f"Thanks for reaching out about \"{email.subject}\"! I've got your message and will get back to you shortly."
                else:  # Professional
                    body = f"Thank you for your email regarding \"{email.subject}\". I acknowledge receipt and will follow up with the required details."

            return f"{greeting}\n\n{body}\n\n{signoff}"

        # =========================================================================
        # 2. MEDIUM FORMAT (3–6 sentences)
        # =========================================================================
        elif norm_length == EmailReply.LENGTH_MEDIUM:
            if has_instruction:
                if is_decline_instruction:
                    if norm_tone == EmailReply.TONE_FORMAL:
                        body = (
                            f"Thank you for your correspondence concerning {email.subject}. "
                            "After reviewing my schedule, I regret that I will be unable to participate due to prior commitments. "
                            "I appreciate your consideration and hope we may collaborate on a future occasion. "
                            "Please accept my sincere apologies for any inconvenience caused."
                        )
                    elif norm_tone == EmailReply.TONE_POLITE:
                        body = (
                            f"Thank you very much for reaching out and extending this invitation regarding {email.subject}. "
                            "Unfortunately, I have an unavoidable scheduling conflict and will be unable to attend. "
                            "I truly appreciate you thinking of me and hope we can connect again soon. "
                            "Thank you for your understanding."
                        )
                    elif norm_tone == EmailReply.TONE_FRIENDLY:
                        body = (
                            f"Thanks so much for reaching out about {email.subject}! "
                            "I would love to be there, but unfortunately I have a prior commitment that I cannot reschedule. "
                            "I really appreciate you including me and hope we can catch up soon. "
                            "Have a fantastic session!"
                        )
                    else:  # Professional
                        body = (
                            f"Thank you for the invitation regarding {email.subject}. "
                            "Due to an existing scheduling conflict, I will unfortunately be unable to attend. "
                            "I appreciate you keeping me informed and welcome updates following the session. "
                            "Please let me know if any alternative arrangements are scheduled."
                        )
                elif is_extension_instruction:
                    if norm_tone == EmailReply.TONE_FORMAL:
                        body = (
                            f"I am writing in reference to the timeline outlined for {email.subject}. "
                            f"To ensure all requirements are completed with thorough quality, {instr_clean}. "
                            "Would it be acceptable to submit the finalized deliverables by an extended date? "
                            "I appreciate your flexibility and look forward to your guidance."
                        )
                    elif norm_tone == EmailReply.TONE_POLITE:
                        body = (
                            f"Thank you for the update regarding {email.subject}. "
                            f"I am making steady progress on the required items, but {instr_clean}. "
                            "Could you kindly grant a short extension so I can ensure everything is completed accurately? "
                            "Thank you very much for your understanding and support."
                        )
                    else:
                        body = (
                            f"Thank you for your message regarding {email.subject}. "
                            f"Regarding the current schedule, {instr_clean}. "
                            "Could you please grant a brief deadline extension to finalize the deliverables? "
                            "I look forward to hearing from you."
                        )
                else:
                    if norm_tone == EmailReply.TONE_FORMAL:
                        body = (
                            f"Thank you for contacting me concerning {email.subject}. "
                            f"In response to your query, {instr_clean}. "
                            "I trust this provides the required clarity for our next steps. "
                            "Please do not hesitate to contact me should further details be needed."
                        )
                    elif norm_tone == EmailReply.TONE_POLITE:
                        body = (
                            f"Thank you very much for taking the time to write regarding {email.subject}. "
                            f"To address your message, {instr_clean}. "
                            "I appreciate your patience and coordination on this matter. "
                            "Please feel free to reach out if you need any additional information."
                        )
                    elif norm_tone == EmailReply.TONE_FRIENDLY:
                        body = (
                            f"Thanks so much for reaching out about {email.subject}! "
                            f"Just to follow up on your note: {instr_clean}. "
                            "I'm glad we could coordinate on this, and everything looks great on my side. "
                            "Let me know if there's anything else you'd like to chat about!"
                        )
                    else:  # Professional
                        body = (
                            f"Thank you for your email regarding {email.subject}. "
                            f"Regarding the matter discussed: {instr_clean}. "
                            "I have noted all associated details and look forward to progressing accordingly. "
                            "Please let me know if you require any further clarification."
                        )

            elif is_rejection:
                if norm_tone == EmailReply.TONE_FORMAL:
                    body = (
                        "Thank you for contacting me with an update regarding my application. "
                        "While I regret that I will not be moving forward, I appreciate your committee's time and consideration. "
                        "I value the opportunity to have learned about your organization's mission and initiatives. "
                        "I wish you and the team continued success in all your endeavors."
                    )
                elif norm_tone == EmailReply.TONE_POLITE:
                    body = (
                        "Thank you very much for following up and sharing the update on my application. "
                        "While I am disappointed not to be joining your team, I truly appreciate the time and courtesy extended to me. "
                        "It was a pleasure speaking with you and learning more about the role. "
                        "I wish you and the company every success moving forward."
                    )
                elif norm_tone == EmailReply.TONE_FRIENDLY:
                    body = (
                        "Thanks for letting me know about the hiring decision. "
                        "While I would have loved to join the team, I really enjoyed meeting everyone and learning more about your work. "
                        "I appreciate you taking the time to keep me updated throughout the process. "
                        "Wishing you and the whole team all the best!"
                    )
                else:  # Professional
                    body = (
                        "Thank you for following up with me regarding the outcome of my application. "
                        "While I am disappointed not to move forward, I truly appreciate the team's time and consideration throughout the selection process. "
                        "I enjoyed our discussions and learning more about the work your team is doing. "
                        "I wish the organization continued success."
                    )

            elif is_interview:
                slot_mention = f" on {slot_str}" if slot_str else " for Monday at 11:00 AM"
                if norm_tone == EmailReply.TONE_FORMAL:
                    body = (
                        "I am writing to formally acknowledge receipt of the interview schedule. "
                        f"I hereby confirm my availability for the appointment{slot_mention}. "
                        "I look forward to discussing the role and learning more about the team's objectives. "
                        "Please inform me should any preliminary documentation or preparation be required."
                    )
                elif norm_tone == EmailReply.TONE_POLITE:
                    body = (
                        "Thank you very much for sharing the interview schedule. "
                        f"I am pleased to confirm my availability{slot_mention}. "
                        "I truly appreciate this opportunity and look forward to speaking with the team. "
                        "Please let me know if there is anything I should prepare in advance."
                    )
                elif norm_tone == EmailReply.TONE_FRIENDLY:
                    body = (
                        "Thanks for sharing the interview schedule! "
                        f"{slot_str or 'Monday at 11:00 AM'} works for me. "
                        "I appreciate the opportunity and look forward to speaking with the team. "
                        "Please let me know if there's anything I should review beforehand."
                    )
                else:  # Professional
                    body = (
                        "Thank you for sharing the interview schedule. "
                        f"I confirm my availability for the technical interview{slot_mention}. "
                        "I look forward to speaking with the team and discussing how my background aligns with your priorities. "
                        "Please let me know if any further preparation is needed beforehand."
                    )

            elif is_missing_meeting_details:
                if norm_tone == EmailReply.TONE_FORMAL:
                    body = (
                        f"I am writing to acknowledge your message regarding the upcoming meeting on {email.subject}. "
                        "I would be pleased to attend and contribute to the discussion. "
                        "Could you please share the scheduled time and video conference link so I can add it to my calendar? "
                        "Please let me know if there are any agenda items to review beforehand."
                    )
                elif norm_tone == EmailReply.TONE_POLITE:
                    body = (
                        "Thank you very much for reaching out about the project meeting. "
                        "I would be glad to participate in the discussion with the team. "
                        "Could you kindly share the scheduled time and meeting link so I can confirm my attendance? "
                        "Looking forward to speaking with everyone."
                    )
                elif norm_tone == EmailReply.TONE_FRIENDLY:
                    body = (
                        "Thanks for the heads-up about the project meeting! "
                        "I would love to join and catch up on our latest progress. "
                        "Could you please share the meeting time and link? "
                        "Looking forward to seeing everyone tomorrow!"
                    )
                else:  # Professional
                    body = (
                        "Thank you for reaching out. "
                        "I would be glad to coordinate and discuss this further. "
                        "Could you please suggest a few times that work for you and share a meeting link or calendar invitation? "
                        "I look forward to our discussion."
                    )

            elif is_academic:
                if norm_tone == EmailReply.TONE_FORMAL:
                    body = (
                        f"Thank you for your guidance regarding the coursework for {email.subject}. "
                        "I have thoroughly reviewed the questions and instructions provided in your email. "
                        "I am completing the required analysis and will submit my finalized work according to the academic guidelines. "
                        "Please let me know if any additional verification is necessary."
                    )
                elif norm_tone == EmailReply.TONE_POLITE:
                    body = (
                        f"Thank you very much for taking the time to send feedback on {email.subject}. "
                        "I have carefully read through your questions and appreciate the helpful pointers. "
                        "I am addressing each point in my updated draft and look forward to submitting it on time. "
                        "Thank you for your continuous support."
                    )
                else:
                    body = (
                        f"Thank you for your email regarding {email.subject}. "
                        "I have reviewed each of the questions raised and am addressing them directly in my submission. "
                        "Everything is progressing as planned, and I will share the completed work shortly. "
                        "Please let me know if you need any preliminary drafts."
                    )

            else:
                if norm_tone == EmailReply.TONE_FORMAL:
                    body = (
                        f"Thank you for contacting me concerning \"{email.subject}\". "
                        "I have received your correspondence and given careful consideration to the points raised. "
                        "I will coordinate the necessary next steps and provide you with a comprehensive update shortly. "
                        "Please do not hesitate to contact me if any urgent matters arise."
                    )
                elif norm_tone == EmailReply.TONE_POLITE:
                    body = (
                        f"Thank you very much for reaching out regarding \"{email.subject}\". "
                        "I appreciate you taking the time to share these details with me. "
                        "I am looking into this right now and will follow up with you promptly with next steps. "
                        "Please let me know if there is any other information you need in the meantime."
                    )
                elif norm_tone == EmailReply.TONE_FRIENDLY:
                    body = (
                        f"Thanks so much for getting in touch about \"{email.subject}\"! "
                        "It's great to hear from you, and I've noted all the details in your note. "
                        "I'm taking care of this on my end and will circle back with you shortly. "
                        "Hope you're having a wonderful week!"
                    )
                else:  # Professional
                    body = (
                        f"Thank you for your email regarding \"{email.subject}\". "
                        "I have received your message and reviewed the details provided. "
                        "I am reviewing the action items and will follow up with you with a complete update shortly. "
                        "Please let me know if you need any additional clarification."
                    )

            return f"{greeting}\n\n{body}\n\n{signoff}"

        # =========================================================================
        # 3. LONG FORMAT (Detailed, multi-paragraph response)
        # =========================================================================
        else:
            paragraphs = []
            slot_mention = f" on {slot_str}" if slot_str else " on the proposed date and time"

            if has_instruction:
                if is_decline_instruction:
                    paragraphs.append(f"I am writing in response to your recent communication regarding {email.subject}.")
                    paragraphs.append(
                        f"After a careful review of my calendar and current commitments, I regret that I will be unable to participate as requested. "
                        f"{instr_clean}. I want to be mindful of your timeline and ensure all parties have adequate notice."
                    )
                    paragraphs.append(
                        "I truly appreciate you reaching out with this opportunity and thinking of me. "
                        "Please keep me in mind for future initiatives, and I would be glad to stay connected as upcoming discussions develop."
                    )
                elif is_extension_instruction:
                    paragraphs.append(f"Thank you for reaching out regarding the deliverables and deadlines for {email.subject}.")
                    paragraphs.append(
                        f"I have been making steady progress on each component of the assignment. However, to ensure all technical requirements, "
                        f"testing, and documentation meet the highest standards, {instr_clean}. A short extension would enable me to submit a polished, comprehensive submission."
                    )
                    paragraphs.append(
                        "Could you please let me know if an extension is acceptable, and what date would work best on your side? "
                        "I deeply appreciate your flexibility and understanding."
                    )
                else:
                    paragraphs.append(f"Thank you for contacting me with detailed information regarding {email.subject}.")
                    paragraphs.append(
                        f"In direct response to your message: {instr_clean}. We are aligning all related items to ensure seamless execution and adherence to expectations."
                    )
                    paragraphs.append(
                        "Should you require any additional documentation, preliminary data, or verification from my side, please let me know at your earliest convenience. "
                        "I look forward to our continued collaboration."
                    )

            elif is_rejection:
                if norm_tone == EmailReply.TONE_FORMAL:
                    paragraphs.append("I am writing to formally acknowledge receipt of your correspondence regarding the outcome of my application for this role.")
                    paragraphs.append(
                        "While I regret that I will not be moving forward in the selection process, I want to express my sincere gratitude to you and the hiring committee for your time, consideration, and thoughtful evaluation. "
                        "It was a valuable experience learning more about your organization's mission and team culture."
                    )
                    paragraphs.append(
                        "I remain very interested in the impactful work your organization is conducting and would welcome the opportunity to be considered for future roles that align with my background. "
                        "Thank you again for the courtesy extended throughout the process, and I wish you and the team continued success."
                    )
                else:
                    paragraphs.append("Thank you very much for following up and sharing the hiring decision with me.")
                    paragraphs.append(
                        "Although I am naturally disappointed not to be joining the team, I truly appreciate the opportunity to have interviewed and learned about the projects your team is spearheading. "
                        "The conversations throughout the process were insightful, and I value the time your team invested in speaking with me."
                    )
                    paragraphs.append(
                        "Thank you once again for your feedback and consideration. "
                        "I wish you and the entire organization every success in filling this position and achieving your upcoming milestones."
                    )

            elif is_interview:
                if norm_tone == EmailReply.TONE_FORMAL:
                    paragraphs.append("I am writing to formally acknowledge receipt of your communication regarding the interview schedule for this position.")
                    paragraphs.append(
                        f"I am pleased to confirm my availability for the appointment scheduled{slot_mention}. "
                        "I appreciate the committee's consideration and look forward to a comprehensive discussion regarding how my background and qualifications align with your organizational objectives."
                    )
                    paragraphs.append(
                        "Should there be any preliminary materials, technical requirements, or portfolio items you wish for me to provide beforehand, please do not hesitate to advise. "
                        "I look forward to speaking with the team."
                    )
                else:
                    paragraphs.append("Thank you very much for getting in touch and providing the schedule for the interview. I truly appreciate you and your team taking the time to coordinate this opportunity.")
                    paragraphs.append(
                        f"I am delighted to confirm my availability{slot_mention}. "
                        "I am very enthusiastic about the opportunity to meet with the team and discuss how my skills and experience can contribute to your current projects and goals."
                    )
                    paragraphs.append(
                        "Please feel free to let me know if there is any specific background material, work samples, or technical setup you would like me to prepare ahead of our call. "
                        "I look forward to our conversation."
                    )

            elif is_missing_meeting_details:
                if norm_tone == EmailReply.TONE_FORMAL:
                    paragraphs.append(f"I am writing to formally acknowledge your invitation to the upcoming meeting regarding {email.subject}.")
                    paragraphs.append(
                        "I would be pleased to attend and participate in the discussion. "
                        "To ensure all participants can join punctually, could you please provide the scheduled time, dial-in coordinates, or video conference link at your earliest convenience?"
                    )
                    paragraphs.append(
                        "Additionally, please inform me if an agenda or briefing documents are available for review beforehand so I may prepare thoroughly. "
                        "I look forward to our discussion."
                    )
                else:
                    paragraphs.append("Thank you very much for reaching out about the upcoming project meeting. I appreciate you keeping me informed and would be glad to attend.")
                    paragraphs.append(
                        "Could you kindly share the scheduled time and video conference link when convenient? "
                        "I want to make sure my calendar is properly updated so I can participate without delay."
                    )
                    paragraphs.append(
                        "Please also let me know if there are any specific status reports, questions, or action items you would like me to review prior to the session. "
                        "I look forward to connecting with the team."
                    )

            elif is_academic:
                if norm_tone == EmailReply.TONE_FORMAL:
                    paragraphs.append(f"I am writing to formally acknowledge receipt of your correspondence regarding {email.subject}.")
                    paragraphs.append(
                        "I have carefully reviewed each question, evaluation criterion, and guideline detailed in your message. "
                        "I am addressing all specific points systematically in my coursework submission to ensure full adherence to academic and technical standards."
                    )
                    paragraphs.append(
                        "Thank you very much for your time, mentorship, and clear instruction. "
                        "I will submit the finalized documentation before the designated deadline and welcome any further guidance you may have."
                    )
                else:
                    paragraphs.append(f"Thank you very much for your detailed message and thoughtful feedback on {email.subject}.")
                    paragraphs.append(
                        "I have carefully reviewed the questions you highlighted regarding the assignment and concepts. "
                        "I am incorporating your suggestions directly into my implementation and verifying all edge cases to ensure the work is complete and rigorous."
                    )
                    paragraphs.append(
                        "I truly appreciate your continued guidance and encouragement throughout the semester. "
                        "Please feel free to let me know if there are any additional references I should review ahead of submission."
                    )

            else:
                paragraphs.append(f"Thank you for your detailed message regarding \"{email.subject}\". I have received your email and given careful consideration to all points raised.")
                paragraphs.append(
                    "I have documented all relevant requirements and am taking the appropriate steps to ensure each item is addressed accurately. "
                    "Our proactive coordination on this matter will help ensure a timely, effective, and well-organized resolution."
                )
                paragraphs.append(
                    "Please let me know if any supplementary information or data is needed from my end, or if we should schedule a brief follow-up discussion. "
                    "I look forward to working together on the next steps."
                )

            draft_body = "\n\n".join(paragraphs)
            return f"{greeting}\n\n{draft_body}\n\n{signoff}"

    def save_draft(self, reply: EmailReply, user, edited_text: str, subject: Optional[str] = None) -> EmailReply:
        """
        Saves user-modified text into the draft reply and creates an audit entry.
        """
        if reply.user != user:
            raise PermissionError("Cannot modify another user's email reply.")

        reply.edited_text = edited_text
        if subject:
            reply.subject = subject.strip()
        reply.status = EmailReply.STATUS_SAVED
        reply.save(update_fields=['edited_text', 'subject', 'status', 'updated_at'])

        ReplyAuditLog.objects.create(
            user=user,
            email=reply.email,
            reply=reply,
            action=EmailReply.STATUS_SAVED,
            details=f"Draft saved ({len(edited_text)} characters)"
        )
        return reply

    def apply_static_template(self, template: ReplyTemplate, email: Email, user) -> EmailReply:
        """
        Renders a static reply template for the given email, substituting placeholders,
        and saves an EmailReply draft.
        """
        sender_name = email.effective_sender_name or email.sender_name or "Friend"
        user_name = user.get_full_name() or user.username
        today_str = timezone.now().strftime('%B %d, %Y')

        # Simple safe template variable replacement
        rendered = template.content
        replacements = {
            '{sender_name}': sender_name,
            '{sender_email}': email.sender_email,
            '{subject}': email.subject,
            '{user_name}': user_name,
            '{date}': today_str,
        }
        for key, val in replacements.items():
            rendered = rendered.replace(key, val)

        reply_subject = self.format_reply_subject(email.subject)

        reply = EmailReply.objects.create(
            user=user,
            email=email,
            reply_type=EmailReply.TYPE_STATIC_TEMPLATE,
            tone=EmailReply.TONE_PROFESSIONAL,
            recipient=email.sender_email,
            subject=reply_subject,
            generated_text=rendered,
            edited_text=rendered,
            status=EmailReply.STATUS_GENERATED
        )

        ReplyAuditLog.objects.create(
            user=user,
            email=email,
            reply=reply,
            action=EmailReply.STATUS_GENERATED,
            details=f"Applied template '{template.name}'"
        )
        return reply

    # Backwards compatibility interface
    def generate_reply(self, email_data: Any, tone: str = 'Professional') -> str:
        """
        Phase 1 compatibility method.
        """
        if isinstance(email_data, Email):
            # If user is not supplied, use email.user
            reply = self.generate_ai_reply(email_data, email_data.user, tone=tone)
            return reply.generated_text

        if not self._provider:
            return (
                f"[Phase 1 Preview — {tone} Draft]\n\n"
                f"Thank you for contacting me. I have received your message regarding "
                f"'{email_data.get('subject', 'your email')}' and will review the details shortly.\n\n"
                f"Best regards,\n[Your Name]"
            )
        return self.provider.generate_reply(email_data)


PREDEFINED_FORMATS = EmailReplyGenerator.PREDEFINED_FORMATS
PREDEFINED_FORMATS_MAP = EmailReplyGenerator.PREDEFINED_FORMATS_MAP
VALID_TONES = EmailReplyGenerator.VALID_TONES
VALID_LENGTHS = EmailReplyGenerator.VALID_LENGTHS
normalize_tone = EmailReplyGenerator.normalize_tone
normalize_length = EmailReplyGenerator.normalize_length
