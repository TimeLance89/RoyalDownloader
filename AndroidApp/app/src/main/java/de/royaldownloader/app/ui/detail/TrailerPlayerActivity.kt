package de.royaldownloader.app.ui.detail

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.ImageButton
import androidx.activity.ComponentActivity
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

class TrailerPlayerActivity : ComponentActivity() {
    private var player: WebView? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val videoId = intent.getStringExtra(EXTRA_VIDEO_ID)
            ?.takeIf { VIDEO_ID.matches(it) }
            ?: return finish()

        WindowCompat.setDecorFitsSystemWindows(window, false)
        hideSystemBars()

        val webView = WebView(this).apply {
            setBackgroundColor(Color.BLACK)
            setLayerType(WebView.LAYER_TYPE_HARDWARE, null)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            webChromeClient = WebChromeClient()
            webViewClient = WebViewClient()
            loadDataWithBaseURL(
                "https://royal-downloader.de/",
                playerHtml(videoId),
                "text/html",
                "UTF-8",
                null,
            )
        }
        player = webView

        val root = FrameLayout(this).apply {
            setBackgroundColor(Color.BLACK)
            addView(
                webView,
                FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                ),
            )
            addView(
                ImageButton(context).apply {
                    setImageResource(android.R.drawable.ic_menu_close_clear_cancel)
                    contentDescription = "Trailer schließen"
                    setColorFilter(Color.WHITE)
                    setBackgroundColor(Color.argb(150, 0, 0, 0))
                    setPadding(dp(12), dp(12), dp(12), dp(12))
                    setOnClickListener { finish() }
                },
                FrameLayout.LayoutParams(dp(48), dp(48), Gravity.TOP or Gravity.END).apply {
                    topMargin = dp(12)
                    marginEnd = dp(12)
                },
            )
        }
        setContentView(root)
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemBars()
    }

    override fun onDestroy() {
        player?.apply {
            stopLoading()
            loadUrl("about:blank")
            removeAllViews()
            destroy()
        }
        player = null
        super.onDestroy()
    }

    private fun hideSystemBars() {
        WindowInsetsControllerCompat(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior =
                WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    companion object {
        private const val EXTRA_VIDEO_ID = "video_id"
        private const val EXTRA_TITLE = "title"
        private val VIDEO_ID = Regex("^[A-Za-z0-9_-]{6,20}$")

        fun intent(context: Context, videoId: String, title: String) =
            Intent(context, TrailerPlayerActivity::class.java)
                .putExtra(EXTRA_VIDEO_ID, videoId)
                .putExtra(EXTRA_TITLE, title)
    }
}

private fun playerHtml(videoId: String) = """
    <!doctype html>
    <html>
      <head>
        <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
        <style>
          html,body,iframe { width:100%; height:100%; margin:0; border:0; background:#000; overflow:hidden; }
        </style>
      </head>
      <body>
        <iframe
          src="https://www.youtube.com/embed/$videoId?autoplay=1&amp;playsinline=1&amp;controls=1&amp;fs=0&amp;rel=0"
          title="YouTube Trailer"
          allow="autoplay; encrypted-media; picture-in-picture"
        ></iframe>
      </body>
    </html>
""".trimIndent()
