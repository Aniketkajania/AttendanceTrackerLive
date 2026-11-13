import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from concurrent.futures import ThreadPoolExecutor
from config import SMTP_ENABLED, SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, SENDER_PASSWORD

# Background thread pool so SMTP network I/O never blocks video frames
email_pool = ThreadPoolExecutor(max_workers=4)

def _send_email_worker(payload: dict):
    if not SMTP_ENABLED:
        print(f"[EMAIL SKIPPED - SMTP_ENABLED=False] Would have emailed {payload['email']} for {payload['event_title']}")
        return

    try:
        msg = MIMEMultipart("related")
        msg["Subject"] = f"[Attendance: {payload['event_title']}] {payload['person_name']} ({payload['employee_id']}) - {payload['camera_location']}"
        msg["From"] = SENDER_EMAIL
        msg["To"] = payload["email"]

        header_color = "#16a34a" if payload["event_type"] == "IN" else "#dc2626"

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #1f2937; background-color: #f3f4f6; padding: 15px;">
            <div style="max-width: 560px; margin: 0 auto; background: #ffffff; border: 1px solid #d1d5db; border-radius: 8px; overflow: hidden;">
                <div style="background-color: {header_color}; color: #ffffff; padding: 14px 20px;">
                    <h2 style="margin: 0; font-size: 18px;">{payload['event_title']} NOTIFICATION</h2>
                </div>
                <div style="padding: 20px;">
                    <p style="margin-top: 0;">Hello <b>{payload['person_name']}</b> (<code>{payload['employee_id']}</code>),</p>
                    <p>Your attendance was recorded at <b>{payload['camera_location']}</b> via camera <code>{payload['camera_id']}</code>.</p>

                    <table style="width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 14px;">
                        <tr style="background: #f9fafb;">
                            <td style="padding: 8px 12px; border: 1px solid #e5e7eb;"><b>Event Type & Time</b></td>
                            <td style="padding: 8px 12px; border: 1px solid #e5e7eb;"><b>{payload['event_type']}</b> at {payload['event_time']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 12px; border: 1px solid #e5e7eb;"><b>First Check-In Today</b></td>
                            <td style="padding: 8px 12px; border: 1px solid #e5e7eb;">{payload['first_check_in']} ({payload['first_check_in_location']})</td>
                        </tr>
                        <tr style="background: #f9fafb;">
                            <td style="padding: 8px 12px; border: 1px solid #e5e7eb;"><b>Latest Check-Out Today</b></td>
                            <td style="padding: 8px 12px; border: 1px solid #e5e7eb;">{payload['last_check_out'] or 'Currently Inside'}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 12px; border: 1px solid #e5e7eb;"><b>Visited Locations Today</b></td>
                            <td style="padding: 8px 12px; border: 1px solid #e5e7eb;">{payload['visited_locations']}</td>
                        </tr>
                        <tr style="background: #f9fafb;">
                            <td style="padding: 8px 12px; border: 1px solid #e5e7eb;"><b>Total Checks Today</b></td>
                            <td style="padding: 8px 12px; border: 1px solid #e5e7eb;">{payload['total_checks']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 12px; border: 1px solid #e5e7eb;"><b>Out of Office Hours</b></td>
                            <td style="padding: 8px 12px; border: 1px solid #e5e7eb;">{payload['out_of_office_hours']:.2f} hrs</td>
                        </tr>
                        <tr style="background: #ecfdf5;">
                            <td style="padding: 8px 12px; border: 1px solid #e5e7eb;"><b>Total Working Hours</b></td>
                            <td style="padding: 8px 12px; border: 1px solid #e5e7eb;"><b>{payload['total_working_hours']:.2f} hrs</b></td>
                        </tr>
                    </table>

                    <p style="font-size: 13px; color: #4b5563; margin-bottom: 6px;"><b>Gate Capture Snapshot:</b></p>
                    <img src="cid:gate_snapshot" style="max-width: 240px; border-radius: 6px; border: 1px solid #9ca3af;" />
                </div>
            </div>
        </body>
        </html>
        """
        msg.attach(MIMEText(html_content, "html"))

        snapshot_path = payload.get("snapshot_path")
        if snapshot_path and os.path.exists(snapshot_path):
            with open(snapshot_path, "rb") as img_file:
                mime_img = MIMEImage(img_file.read())
                mime_img.add_header("Content-ID", "<gate_snapshot>")
                mime_img.add_header("Content-Disposition", "inline", filename=os.path.basename(snapshot_path))
                msg.attach(mime_img)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=12) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)

        print(f"[EMAIL SENT] Sent '{payload['event_title']}' notification to {payload['email']}")
    except Exception as e:
        print(f"[EMAIL ERROR] Failed sending to {payload['email']}: {e}")

def send_attendance_email_async(payload: dict):
    """Submits email payload to background thread pool immediately."""
    email_pool.submit(_send_email_worker, payload)