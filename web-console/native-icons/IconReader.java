package org.jiuliu.awd;

import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.drawable.Drawable;
import android.os.Looper;
import android.util.Base64;
import java.io.ByteArrayOutputStream;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;

/** Render installed application resources using Android, not an APK filename heuristic. */
public final class IconReader {
    public static void main(String[] args) {
        try {
            if (args.length != 1 || !args[0].matches("[A-Za-z0-9_]+(\\.[A-Za-z0-9_]+)+")) {
                throw new IllegalArgumentException("invalid package");
            }
            if (Looper.getMainLooper() == null) Looper.prepareMainLooper();
            // app_process is a shell Java entry point. No root is requested.
            // ActivityThread is not a public SDK API; unsupported firmware falls back.
            Class<?> thread = Class.forName("android.app.ActivityThread");
            Object instance = thread.getMethod("systemMain").invoke(null);
            Method systemContext = thread.getMethod("getSystemContext");
            Context context = (Context) systemContext.invoke(instance);
            PackageManager pm = context.getPackageManager();
            ApplicationInfo info = pm.getApplicationInfo(args[0], 0);
            CharSequence label = pm.getApplicationLabel(info);
            Drawable icon = pm.getApplicationIcon(info);
            Bitmap bitmap = Bitmap.createBitmap(96, 96, Bitmap.Config.ARGB_8888);
            icon.setBounds(0, 0, 96, 96);
            icon.draw(new Canvas(bitmap));
            ByteArrayOutputStream png = new ByteArrayOutputStream();
            if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, png)) {
                throw new IllegalStateException("icon encode failed");
            }
            bitmap.recycle();
            System.out.println("AWD_ICON_V1\t" +
                Base64.encodeToString(label.toString().getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP) + "\t" +
                Base64.encodeToString(png.toByteArray(), Base64.NO_WRAP));
            System.out.flush();
            System.exit(0);
        } catch (Throwable error) {
            System.err.println("icon reader unavailable: " + error.getClass().getSimpleName());
            System.exit(1);
        }
    }
}
