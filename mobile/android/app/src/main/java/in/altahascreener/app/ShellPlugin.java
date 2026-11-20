package in.altahascreener.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.print.PrintAttributes;
import android.print.PrintManager;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * The two things the pages need from the phone that no published plugin
 * gives them. Called from mobile/src/bridge.js as "AltahaShell".
 *
 * print          window.print() does nothing in a web view. This opens the
 *                system print dialog, which is also "Save as PDF". With no
 *                html it prints the page on screen; with html it prints that
 *                document instead (the portfolio report, which the site
 *                writes into a new window).
 *
 * setBackground  The colour behind the page. A page is blank for a moment
 *                while it loads, and that moment is this colour. It follows
 *                the site's light or dark appearance, and it is remembered so
 *                the next launch starts on the right one.
 */
@CapacitorPlugin(name = "AltahaShell")
public class ShellPlugin extends Plugin {

    static final String PREFS = "altaha_shell";
    static final String KEY_BACKGROUND = "background";

    /** Kept until the print job has read it; a collected view prints nothing. */
    private WebView printView;

    @PluginMethod
    public void print(final PluginCall call) {
        final String name = call.getString("name", "Altaha Screener");
        final String html = call.getString("html");
        final String baseUrl = call.getString("baseUrl", "https://altahascreener.in/");

        getActivity().runOnUiThread(() -> {
            try {
                final PrintManager manager = (PrintManager) getActivity().getSystemService(Context.PRINT_SERVICE);
                if (manager == null) {
                    call.reject("Printing is not available on this device.");
                    return;
                }
                final PrintAttributes attributes = new PrintAttributes.Builder().build();

                if (html == null || html.isEmpty()) {
                    manager.print(name, bridge.getWebView().createPrintDocumentAdapter(name), attributes);
                    call.resolve();
                    return;
                }

                printView = new WebView(getActivity());
                printView.setWebViewClient(new WebViewClient() {
                    @Override
                    public void onPageFinished(WebView view, String url) {
                        manager.print(name, view.createPrintDocumentAdapter(name), attributes);
                        call.resolve();
                    }
                });
                printView.loadDataWithBaseURL(baseUrl, html, "text/html", "UTF-8", null);
            } catch (Exception e) {
                call.reject("Could not open the print dialog.", e);
            }
        });
    }

    @PluginMethod
    public void setBackground(final PluginCall call) {
        final String value = call.getString("color", "");
        final int color;
        try {
            color = Color.parseColor(value);
        } catch (Exception e) {
            call.reject("Not a colour: " + value);
            return;
        }

        SharedPreferences prefs = getContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        prefs.edit().putInt(KEY_BACKGROUND, color).apply();

        getActivity().runOnUiThread(() -> {
            MainActivity.paint(getActivity(), bridge.getWebView(), color);
            call.resolve();
        });
    }
}
