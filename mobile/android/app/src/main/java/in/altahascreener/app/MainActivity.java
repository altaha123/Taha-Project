package in.altahascreener.app;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.graphics.drawable.ColorDrawable;
import android.os.Bundle;
import android.webkit.WebView;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    /* The site's page colour in each appearance (--paper in frontend/index.html
       and frontend/altaha-skin.css). */
    static final int PAPER_LIGHT = 0xFFFBFAF7;
    static final int PAPER_DARK = 0xFF0C0B08;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Before super: the bridge reads the list of plugins as it starts.
        registerPlugin(ShellPlugin.class);
        super.onCreate(savedInstanceState);

        if (getBridge() != null) {
            paint(this, getBridge().getWebView(), startingBackground());
        }
    }

    /**
     * The colour the last page asked for, so somebody who chose the dark
     * appearance on a phone set to light does not get a white flash at launch.
     * On the first launch there is no such colour, and the site follows the
     * phone's own setting, so this does too.
     */
    private int startingBackground() {
        SharedPreferences prefs = getSharedPreferences(ShellPlugin.PREFS, Context.MODE_PRIVATE);
        if (prefs.contains(ShellPlugin.KEY_BACKGROUND)) {
            return prefs.getInt(ShellPlugin.KEY_BACKGROUND, PAPER_LIGHT);
        }
        int night = getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK;
        return night == Configuration.UI_MODE_NIGHT_YES ? PAPER_DARK : PAPER_LIGHT;
    }

    static void paint(Activity activity, WebView webView, int color) {
        if (webView != null) {
            webView.setBackgroundColor(color);
        }
        if (activity != null && activity.getWindow() != null) {
            activity.getWindow().setBackgroundDrawable(new ColorDrawable(color));
        }
    }
}
