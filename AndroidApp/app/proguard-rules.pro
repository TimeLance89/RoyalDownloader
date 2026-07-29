# Retrofit ships consumer rules for annotated service interfaces; Kotlin
# Serialization generates direct serializer references. Keep only metadata
# required for generic suspend signatures and runtime annotations.
-keepattributes Signature,InnerClasses,EnclosingMethod,*Annotation*
-dontwarn org.codehaus.mojo.animal_sniffer.IgnoreJRERequirement
