"""Email helpers — transactional email via Resend."""
import os
import resend


def send_password_reset_email(to_email: str, reset_link: str) -> None:
    resend.api_key = os.environ["RESEND_API_KEY"]
    resend.Emails.send({
        "from": os.environ.get("RESEND_FROM", "onboarding@resend.dev"),
        "to": [to_email],
        "subject": "Reset your Cynda password",
        "html": f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#0F1117;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0F1117;padding:40px 0;">
    <tr><td align="center">
      <table width="480" cellpadding="0" cellspacing="0" style="background:#181C27;border-radius:12px;border:1px solid #252A38;">
        <tr>
          <td style="padding:32px 40px 24px;border-bottom:1px solid #252A38;">
            <span style="font-size:22px;font-weight:700;color:#F25C1E;letter-spacing:-0.5px;">Cynda</span>
          </td>
        </tr>
        <tr>
          <td style="padding:32px 40px;">
            <p style="margin:0 0 16px;font-size:15px;color:#E8E8E4;line-height:1.6;">Hi,</p>
            <p style="margin:0 0 28px;font-size:15px;color:#E8E8E4;line-height:1.6;">
              We received a request to reset the password for your Cynda account.<br>
              Click the button below to choose a new one.
            </p>
            <a href="{reset_link}" style="display:inline-block;background:#F25C1E;color:#0F1117;text-decoration:none;font-weight:600;font-size:15px;padding:13px 28px;border-radius:10px;">Reset password</a>
            <p style="margin:28px 0 0;font-size:13px;color:#6E7484;line-height:1.6;">
              This link expires in <strong style="color:#E8E8E4;">1 hour</strong>.
              If you didn't request a password reset, you can safely ignore this email — your account remains secure.
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 40px;border-top:1px solid #252A38;">
            <p style="margin:0;font-size:12px;color:#6E7484;">Cynda &middot; Questions? Reply to this email.</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>""",
    })
