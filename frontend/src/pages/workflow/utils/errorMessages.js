import i18n from '../../../i18n';

export function mapWorkflowError(rawError) {
  if (!rawError) return i18n.t('workflow:toasts.unknownError', 'An unknown error occurred.');

  const lower = rawError.toLowerCase();

  if (lower.includes('rate_limit') || lower.includes('rate limit')) {
    return i18n.t('workflow:toasts.rateLimitError');
  }
  if (lower.includes('invalid_prompt') || lower.includes('safety') || lower.includes('blocked')) {
    return i18n.t('workflow:toasts.promptRejected');
  }
  if (lower.includes('image_too_large') || lower.includes('image too large')) {
    return i18n.t('workflow:toasts.imageTooLarge');
  }
  if (lower.includes('model_not_found') || lower.includes('404')) {
    return i18n.t('workflow:toasts.modelNotFound');
  }

  return rawError.trim().slice(0, 200);
}
