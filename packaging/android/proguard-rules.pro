# Kryon's native host looks up the activity's public entry points through JNI.
# Keep their names and the native callbacks registered against this class.
-keep,allowoptimization class xyz.waozi.shovey.ShoveyActivity {
    public <methods>;
    native <methods>;
}

# Native notification registration looks up this class and its methods by name.
-keep,allowoptimization class org.kryonlabs.notifications.NotificationReceiver {
    native <methods>;
}

# Present only in the Google Play edition; its native bridge uses this entry.
-keep,allowoptimization class org.kryonlabs.play.PlayBilling {
    public static java.lang.String call(android.app.Activity, java.lang.String);
}
